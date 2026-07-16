"""CCR Platform - FastAPI application.

Single deployable: serves the JSON API under /api and the prebuilt React
dashboard as static files at /. Local-first by design: corpora, embeddings,
and results never leave this machine (sentence-transformers runs locally),
which keeps sensitive research text IRB-friendly and every run reproducible
against pinned model weights.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import auth, auth_google, retention, storage
from . import jobs as jobs_module
from . import registry
from .ccr import FAKE_MODEL_NAME
from .construct_files import parse_construct_file
from .construct_lib import sync_library
from .db import DATA_DIR, Base, SessionLocal, auto_migrate_sqlite, engine, get_db
from .ingest import IngestError, load_corpus, suggest_text_column
from .models import Construct, Corpus, Job, Project, User
from .reproducibility import requirements_text, script_text
from .schemas import (
    ConstructCreate,
    ConstructOut,
    CorpusOut,
    JobCreate,
    JobOut,
    LoginIn,
    ProjectCreate,
    ProjectOut,
    ProjectPatch,
    RegisterIn,
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # sane lab-scale ceiling; raise deliberately
ALLOWED_SUFFIXES = (".csv", ".xlsx", ".xls")

# Languages offered in the UI selector; detection may report others (ISO 639-1).
SELECTABLE_LANGUAGES = [
    "en", "es", "fr", "de", "it", "pt", "nl", "ru", "zh", "ja", "ko", "ar", "hi", "tr", "fa",
]

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create tables and sync the construct library (YAML source of truth) at startup."""
    Base.metadata.create_all(engine)
    auto_migrate_sqlite(engine, Base.metadata)  # additive column adds for existing dev DBs
    registry.list_models()  # fail fast on an invalid models.yaml
    db = SessionLocal()
    try:
        sync_library(db)
    finally:
        db.close()
    jobs_module.recover_orphaned_jobs()
    retention.start_cleanup()  # anonymous-data TTL purge (no-op if CCR_ANON_TTL_HOURS=0)
    if os.environ.get("CCR_WARM_MODEL") == "1" and os.environ.get("CCR_FAKE_EMBEDDINGS") != "1":
        import threading

        def _warm():
            try:
                from .ccr import get_backend

                get_backend(registry.default_model().id).encode(["warm up"])
            except Exception:
                pass  # first real run will load the model instead

        threading.Thread(target=_warm, daemon=True, name="ccr-warmup").start()
    yield
    retention.stop_cleanup()
    jobs_module.shutdown_executor()


app = FastAPI(title="CCR Platform", version="0.1.0", lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=1024)  # constructs payload + SPA compress ~4-5x
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- helpers
def _construct_out(c: Construct) -> ConstructOut:
    items = json.loads(c.items_json)
    flags = json.loads(c.reverse_flags_json or "[]") or [False] * len(items)
    return ConstructOut(
        id=c.id,
        name=c.name,
        description=c.description,
        reference=c.reference,
        items=items,
        reverse_scored=flags,
        is_seed=c.is_seed,
        version=c.version or 1,
        verification_status=c.verification_status or "draft",
        language=c.language or "en",
        category=c.category or "",
        item_hash=(c.item_hash or "")[:16],
    )


def _job_out(db: Session, j: Job) -> JobOut:
    construct = db.get(Construct, j.construct_id)
    corpus = db.get(Corpus, j.corpus_id)
    return JobOut(
        id=j.id,
        project_id=j.project_id,
        corpus_id=j.corpus_id,
        construct_id=j.construct_id,
        construct_name=construct.name if construct else "",
        corpus_filename=corpus.filename if corpus else "",
        text_column=j.text_column,
        model_name=j.model_name,
        language=j.language or "en",
        status=j.status,
        progress=j.progress,
        error=j.error,
        created_at=j.created_at,
        started_at=j.started_at,
        finished_at=j.finished_at,
    )


def _get_or_404(db: Session, model, obj_id: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj


# ------------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    try:
        import sentence_transformers  # noqa: F401

        st = True
    except ImportError:
        st = False
    return {"status": "ok", "sentence_transformers_available": st}


@app.get("/api/models")
def list_models():
    """Model options from the registry (spec 0003) - never hardcoded."""
    return [
        {
            "id": m.id,
            "label": m.display_name,
            "default": m.default,
            "languages": (m.language_set_name or ", ".join(sorted(m.supported_languages)) or "unspecified"),
            "speed_tier": m.speed_tier,
            "quality_tier": m.quality_tier,
            "warnings": list(m.user_warnings),
        }
        for m in registry.list_models()
    ]


@app.get("/api/languages")
def list_languages():
    return SELECTABLE_LANGUAGES


# ------------------------------------------------------------------ accounts
# Local email+password accounts (auth.py) - the free interim provider. The
# managed swap (Supabase: Google + email/password) replaces token issuance
# only; every other endpoint just depends on auth.get_current_user.
def _saved_runs_used(db: Session, user_id: str) -> int:
    return (
        db.query(Job)
        .join(Project, Job.project_id == Project.id)
        .filter(Project.owner_user_id == user_id, Job.status.in_(("queued", "running", "completed")))
        .count()
    )


def _set_session_cookie(response: Response, user: User) -> None:
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.create_session_token(user.id, user.email, user.name),
        httponly=True,
        samesite="lax",
        secure=auth.cookies_secure(),
        max_age=30 * 24 * 3600,
    )


@app.get("/api/auth/me")
def auth_me(
    request: Request,
    db: Session = Depends(get_db),
    user: dict | None = Depends(auth.get_current_user),
):
    if user:
        return {
            "signed_in": True,
            "name": user["name"],
            "email": user["email"],
            "limits": {"max_bytes": MAX_UPLOAD_BYTES, "max_rows": None},
            "usage": {
                "saved_runs": _saved_runs_used(db, user["id"]),
                "max_saved_runs": auth.user_max_saved_runs(),
            },
        }
    return {
        "signed_in": False,
        "name": None,
        "email": None,
        "google_available": auth_google.configured(),
        "limits": {"max_bytes": auth.anon_max_bytes(), "max_rows": auth.anon_max_rows()},
        "usage": {
            "runs_used_today": auth.runs_used_today(request),
            "max_runs_per_day": auth.anon_max_runs_per_day(),
        },
    }


@app.post("/api/auth/register", status_code=201)
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not auth.valid_email(email):
        raise HTTPException(400, "Please enter a valid email address.")
    if len(body.password) < auth.MIN_PASSWORD_LEN:
        raise HTTPException(400, f"Password must be at least {auth.MIN_PASSWORD_LEN} characters.")
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    user = User(email=email, name=body.name.strip(), password_hash=auth.hash_password(body.password))
    db.add(user)
    db.commit()
    _set_session_cookie(response, user)
    return {"signed_in": True, "name": user.name, "email": user.email}


@app.post("/api/auth/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.query(User).filter_by(email=email).first()
    if user is not None and not user.password_hash:
        raise HTTPException(401, "This account uses Google sign-in - use the Google button.")
    if user is None or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password.")
    _set_session_cookie(response, user)
    return {"signed_in": True, "name": user.name, "email": user.email}


@app.get("/api/auth/google/login")
def google_login():
    """Start the Google sign-in flow (Supabase PKCE). Plain redirect - the
    frontend links here directly, no SDK involved."""
    if not auth_google.configured():
        raise HTTPException(503, "Google sign-in is not configured on this instance.")
    from fastapi.responses import RedirectResponse

    url, verifier = auth_google.begin()
    resp = RedirectResponse(url, status_code=307)
    resp.set_cookie(
        auth_google.VERIFIER_COOKIE,
        auth.sign_payload({"v": verifier}),
        httponly=True,
        samesite="lax",
        secure=auth.cookies_secure(),
        max_age=auth_google.VERIFIER_TTL_SECONDS,
    )
    return resp


@app.get("/api/auth/google/callback")
def google_callback(request: Request, code: str = "", db: Session = Depends(get_db)):
    from fastapi.responses import RedirectResponse

    def fail(msg: str):
        return RedirectResponse(f"/?auth_error={msg}", status_code=307)

    if not auth_google.configured():
        return fail("google-not-configured")
    payload = auth.verify_payload(request.cookies.get(auth_google.VERIFIER_COOKIE))
    if not code or not payload or "v" not in payload:
        return fail("sign-in-expired-try-again")
    try:
        info = auth_google.exchange(code, payload["v"])
    except ValueError:
        return fail("google-exchange-failed")

    user = db.query(User).filter_by(email=info["email"]).first()
    if user is None:
        # Google-verified account: no local password (password login is refused
        # with a pointer to the Google button).
        user = User(email=info["email"], name=info["name"], password_hash="")
        db.add(user)
        db.commit()

    resp = RedirectResponse("/", status_code=307)
    resp.delete_cookie(auth_google.VERIFIER_COOKIE)
    _set_session_cookie(resp, user)
    return resp


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"signed_in": False}


# --------------------------------------------------------------- projects
def _visible_owners(user: dict | None) -> tuple[str, ...]:
    """Anonymous viewers see anonymous projects; signed-in users additionally
    see their own. Other users' projects are invisible (and untouchable)."""
    return ("",) if user is None else ("", user["id"])


def _require_project_access(project: Project, user: dict | None) -> None:
    if project.owner_user_id and (user is None or project.owner_user_id != user["id"]):
        raise HTTPException(403, "This project belongs to another account.")


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: dict | None = Depends(auth.get_current_user)):
    """Projects ordered by last activity (latest run, else creation) - the
    project a researcher wants is almost always the one they last worked on."""
    from sqlalchemy import func

    activity = {
        pid: (last, count)
        for pid, last, count in db.query(
            Job.project_id, func.max(Job.created_at), func.count(Job.id)
        )
        .group_by(Job.project_id)
        .all()
    }
    rows = db.query(Project).filter(Project.owner_user_id.in_(_visible_owners(user))).all()
    out = []
    for p in rows:
        last, count = activity.get(p.id, (None, 0))
        out.append(
            ProjectOut(
                id=p.id,
                name=p.name,
                description=p.description,
                created_at=p.created_at,
                last_activity_at=last or p.created_at,
                n_runs=count,
                archived=bool(p.archived),
            )
        )
    out.sort(key=lambda x: x.last_activity_at, reverse=True)
    return out


@app.post("/api/projects", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: dict | None = Depends(auth.get_current_user),
):
    project = Project(
        name=body.name.strip(),
        description=body.description.strip(),
        owner_user_id=user["id"] if user else "",  # "" = anonymous (TTL purge applies)
    )
    db.add(project)
    db.commit()
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        last_activity_at=project.created_at,
        n_runs=0,
        archived=False,
    )


@app.patch("/api/projects/{project_id}", response_model=ProjectOut)
def patch_project(
    project_id: str,
    body: ProjectPatch,
    db: Session = Depends(get_db),
    user: dict | None = Depends(auth.get_current_user),
):
    """Archive/unarchive - reversible, no data loss. Archived projects collapse
    into the sidebar's Archived section and keep all datasets and runs."""
    project = _get_or_404(db, Project, project_id)
    _require_project_access(project, user)
    if body.archived is not None:
        project.archived = bool(body.archived)
    db.commit()
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        last_activity_at=project.created_at,
        n_runs=0,
        archived=bool(project.archived),
    )


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: dict | None = Depends(auth.get_current_user),
):
    """Permanent delete: removes the project, its datasets, runs, uploaded
    files, result files, and cached embeddings. Logged without retaining any
    uploaded text (design doc §9)."""
    import logging

    project = _get_or_404(db, Project, project_id)
    _require_project_access(project, user)
    counts = retention.delete_project_cascade(db, project)
    logging.getLogger("ccr.projects").info(
        "project deleted: id=%s name=%r corpora=%d runs=%d",
        project_id, project.name, counts["corpora"], counts["runs"],
    )
    return Response(status_code=204)


# ----------------------------------------------------------------- corpora
@app.get("/api/projects/{project_id}/corpora", response_model=list[CorpusOut])
def list_corpora(project_id: str, db: Session = Depends(get_db)):
    _get_or_404(db, Project, project_id)
    rows = (
        db.query(Corpus)
        .filter_by(project_id=project_id)
        .order_by(Corpus.created_at.desc())
        .all()
    )
    return [
        CorpusOut(
            id=c.id,
            project_id=c.project_id,
            filename=c.filename,
            n_rows=c.n_rows,
            columns=json.loads(c.columns_json),
            suggested_text_column=c.suggested_text_column or None,
            parse_info=json.loads(c.parse_info_json or "{}"),
            created_at=c.created_at,
        )
        for c in rows
    ]


@app.post("/api/projects/{project_id}/corpora", response_model=CorpusOut, status_code=201)
async def upload_corpus(
    project_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    user: dict | None = Depends(auth.get_current_user),
):
    project = _get_or_404(db, Project, project_id)
    _require_project_access(project, user)

    suffix = Path(file.filename or "upload.csv").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Use CSV or XLSX.")

    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File exceeds the 25 MB upload limit.")

    # Tier gate (design §5.1): anonymous users get strict caps; signing in
    # lifts them.
    if user is None and len(payload) > auth.anon_max_bytes():
        mb = auth.anon_max_bytes() // (1024 * 1024)
        raise HTTPException(
            413,
            f"Anonymous uploads are limited to {mb} MB. Sign in (top right) to upload larger files.",
        )

    corpus = Corpus(
        project_id=project_id, filename=file.filename, path="", n_rows=0, columns_json="[]"
    )
    # Parse from a local temp file, then hand the bytes to the storage backend
    # (local disk by default; S3/R2 when CCR_STORAGE=s3 in production).
    tmp_dir = DATA_DIR / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    tmp = tmp_dir / f"{corpus.id}{suffix}"
    tmp.write_bytes(payload)

    try:
        df, parse_info = load_corpus(str(tmp))
    except IngestError as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc

    if user is None and len(df) > auth.anon_max_rows():
        tmp.unlink(missing_ok=True)
        raise HTTPException(
            400,
            f"Anonymous uploads are limited to {auth.anon_max_rows():,} rows "
            f"(this file has {len(df):,}). Sign in (top right) to upload larger corpora.",
        )

    corpus.path = storage.move_local_into_storage("corpora", f"{corpus.id}{suffix}", tmp)

    corpus.n_rows = int(len(df))
    corpus.columns_json = json.dumps(list(df.columns))
    corpus.parse_info_json = json.dumps(parse_info)
    corpus.suggested_text_column = suggest_text_column(df) or ""
    db.add(corpus)
    db.commit()

    preview = json.loads(df.head(5).to_json(orient="records", force_ascii=False))
    return CorpusOut(
        id=corpus.id,
        project_id=project_id,
        filename=corpus.filename,
        n_rows=corpus.n_rows,
        columns=json.loads(corpus.columns_json),
        suggested_text_column=corpus.suggested_text_column or None,
        parse_info=parse_info,
        preview=preview,
        created_at=corpus.created_at,
    )


# -------------------------------------------------------------- constructs
@app.get("/api/constructs", response_model=list[ConstructOut])
def list_constructs(db: Session = Depends(get_db)):
    rows = db.query(Construct).order_by(Construct.is_seed.desc(), Construct.name).all()
    return [_construct_out(c) for c in rows]


@app.post("/api/constructs", response_model=ConstructOut, status_code=201)
def create_construct(body: ConstructCreate, db: Session = Depends(get_db)):
    items = [i.strip() for i in body.items if i.strip()]
    if not items:
        raise HTTPException(400, "Construct needs at least one non-empty item.")
    flags = body.reverse_scored or [False] * len(items)
    if len(flags) != len(items):
        raise HTTPException(400, "reverse_scored must have one flag per item.")
    construct = Construct(
        name=body.name.strip(),
        description=body.description.strip(),
        reference=body.reference.strip(),
        items_json=json.dumps(items),
        reverse_flags_json=json.dumps([bool(f) for f in flags]),
        is_seed=False,
        verification_status="draft",  # user-defined research tools, not validated scales
        language=(body.language or "en").lower(),
    )
    db.add(construct)
    db.commit()
    return _construct_out(construct)


@app.post("/api/constructs/parse-file")
async def parse_construct_upload(file: UploadFile):
    """Parse a CSV/XLSX of scale items into a PREVIEW (nothing is saved).
    The researcher reviews/edits, then saves via POST /api/constructs."""
    suffix = Path(file.filename or "items.csv").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Use CSV or XLSX.")
    payload = await file.read()
    if len(payload) > 1024 * 1024:
        raise HTTPException(413, "Item files are capped at 1 MB (a scale is a short list).")

    tmp_dir = DATA_DIR / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    tmp = tmp_dir / f"construct_upload_{os.urandom(6).hex()}{suffix}"
    tmp.write_bytes(payload)
    try:
        parsed = parse_construct_file(str(tmp))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp.unlink(missing_ok=True)  # item files are never retained

    stem = Path(file.filename or "").stem.replace("_", " ").replace("-", " ").strip()
    parsed["suggested_name"] = stem.title() if stem else ""
    return parsed


# -------------------------------------------------------------------- jobs
@app.post("/api/jobs", response_model=JobOut, status_code=201)
def create_job(
    body: JobCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: dict | None = Depends(auth.get_current_user),
):
    project = _get_or_404(db, Project, body.project_id)
    _require_project_access(project, user)
    corpus = _get_or_404(db, Corpus, body.corpus_id)
    _get_or_404(db, Construct, body.construct_id)

    # Anonymous tier: N runs per day, then sign-in (PI decision 2026-07-10).
    # Cookie counter = a nudge, not a security boundary (recorded in DECISIONS.md).
    if user is None:
        used = auth.runs_used_today(request)
        if used >= auth.anon_max_runs_per_day():
            raise HTTPException(
                429,
                f"Anonymous limit reached ({auth.anon_max_runs_per_day()} runs/day). "
                "Sign in (top right) to keep running - accounts are free.",
            )
    else:
        # Signed-in tier: saved-run cap instead of deletion (their data, their call).
        if _saved_runs_used(db, user["id"]) >= auth.user_max_saved_runs():
            raise HTTPException(
                409,
                f"You have {auth.user_max_saved_runs()} saved runs (the maximum). "
                "Delete a project or old runs to start a new analysis.",
            )

    if body.text_column not in json.loads(corpus.columns_json):
        raise HTTPException(400, f"Column '{body.text_column}' not in corpus columns.")
    allowed = registry.known_ids() | {FAKE_MODEL_NAME}
    if body.model_name not in allowed:
        raise HTTPException(400, f"Unknown model '{body.model_name}'.")
    language = (body.language or "en").strip().lower()
    if not (2 <= len(language) <= 8 and language.replace("-", "").isalpha()):
        raise HTTPException(400, f"Invalid language code '{body.language}'.")

    # Retention: anonymous uploads are deleted after their analysis, so a
    # re-run needs a fresh upload (or an account, where data persists).
    if not corpus.path or not storage.exists(corpus.path):
        raise HTTPException(
            410,
            "This dataset's file was removed after analysis (anonymous uploads are "
            "not kept). Upload the file again, or sign in to keep datasets.",
        )

    job = Job(
        project_id=body.project_id,
        corpus_id=body.corpus_id,
        construct_id=body.construct_id,
        text_column=body.text_column,
        model_name=body.model_name,
        language=language,
    )
    db.add(job)
    db.commit()
    jobs_module.submit_job(job.id)

    if user is None:  # advance the daily counter only after the job is accepted
        response.set_cookie(
            auth.RUNS_COOKIE_NAME,
            auth.run_counter_token(auth.runs_used_today(request) + 1),
            httponly=True,
            samesite="lax",
            secure=auth.cookies_secure(),
            max_age=24 * 3600,
        )
    return _job_out(db, job)


@app.get("/api/jobs", response_model=list[JobOut])
def list_jobs(project_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(Job).filter_by(project_id=project_id).order_by(Job.created_at.desc()).all()
    )
    return [_job_out(db, j) for j in rows]


@app.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    return _job_out(db, _get_or_404(db, Job, job_id))


@app.get("/api/jobs/{job_id}/results")
def job_results(job_id: str, db: Session = Depends(get_db)):
    job = _get_or_404(db, Job, job_id)
    if job.status != "completed":
        raise HTTPException(409, f"Job status is '{job.status}', not completed.")
    return {
        "summary": json.loads(job.summary_json),
        "metadata": json.loads(job.metadata_json),
    }


@app.get("/api/jobs/{job_id}/export")
def export_results(job_id: str, db: Session = Depends(get_db)):
    job = _get_or_404(db, Job, job_id)
    if job.status != "completed" or not job.result_path:
        raise HTTPException(409, "Results not available.")
    filename = f"ccr_results_{job_id[:8]}.csv"
    if storage.is_s3(job.result_path):
        from fastapi.responses import StreamingResponse

        return StreamingResponse(
            storage.open_stream(job.result_path),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return FileResponse(job.result_path, media_type="text/csv", filename=filename)


@app.get("/api/jobs/{job_id}/metadata")
def export_metadata(job_id: str, db: Session = Depends(get_db)):
    job = _get_or_404(db, Job, job_id)
    if job.status != "completed":
        raise HTTPException(409, "Metadata not available.")
    return JSONResponse(
        json.loads(job.metadata_json),
        headers={
            "Content-Disposition": f'attachment; filename="ccr_run_{job_id[:8]}.json"'
        },
    )


@app.get("/api/jobs/{job_id}/script")
def export_script(job_id: str, db: Session = Depends(get_db)):
    """Offline-runnable reproduction script generated from run metadata (spec 0002)."""
    job = _get_or_404(db, Job, job_id)
    if job.status != "completed":
        raise HTTPException(409, "Script not available until the run completes.")
    return PlainTextResponse(
        script_text(json.loads(job.metadata_json)),
        media_type="text/x-python",
        headers={
            "Content-Disposition": f'attachment; filename="reproduce_analysis_{job_id[:8]}.py"'
        },
    )


@app.get("/api/jobs/{job_id}/script-requirements")
def export_script_requirements(job_id: str, db: Session = Depends(get_db)):
    job = _get_or_404(db, Job, job_id)
    if job.status != "completed":
        raise HTTPException(409, "Requirements not available until the run completes.")
    return PlainTextResponse(
        requirements_text(json.loads(job.metadata_json)),
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="requirements-repro_{job_id[:8]}.txt"'
        },
    )


# ------------------------------------------------------------ tester guide + samples
# /guide and /samples exist for the dev instance: a click-through testing guide
# for the PI/students and the synthetic demo corpora it references. guide.html
# lives in app/ (not static/, which `npm run build` wipes); sample_data/ sits at
# the repo root, same resolution as packages/ (= / in the container).
GUIDE_HTML = Path(__file__).resolve().parent / "guide.html"
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "sample_data"


@app.get("/guide", include_in_schema=False)
def testing_guide():
    if not GUIDE_HTML.exists():
        raise HTTPException(404, "Guide not available on this instance.")
    return FileResponse(GUIDE_HTML, media_type="text/html")


if SAMPLES_DIR.exists():
    app.mount("/samples", StaticFiles(directory=SAMPLES_DIR), name="samples")

# ------------------------------------------------------------ static (SPA)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
