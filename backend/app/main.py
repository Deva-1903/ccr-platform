"""CCR Platform — FastAPI application.

Single deployable: serves the JSON API under /api and the prebuilt React
dashboard as static files at /. Local-first by design: corpora, embeddings,
and results never leave this machine (sentence-transformers runs locally),
which keeps sensitive research text IRB-friendly and every run reproducible
against pinned model weights.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import jobs as jobs_module
from .ccr import AVAILABLE_MODELS, FAKE_MODEL_NAME
from .db import DATA_DIR, Base, SessionLocal, engine, get_db
from .ingest import IngestError, load_corpus, suggest_text_column
from .models import Construct, Corpus, Job, Project
from .schemas import (
    ConstructCreate,
    ConstructOut,
    CorpusOut,
    JobCreate,
    JobOut,
    ProjectCreate,
    ProjectOut,
)
from .seed_constructs import SEED_CONSTRUCTS

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # sane lab-scale ceiling; raise deliberately
ALLOWED_SUFFIXES = (".csv", ".xlsx", ".xls")

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create tables and seed the construct library once at startup."""
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if db.query(Construct).filter_by(is_seed=True).count() == 0:
            for seed in SEED_CONSTRUCTS:
                db.add(
                    Construct(
                        name=seed["name"],
                        description=seed["description"],
                        reference=seed["reference"],
                        items_json=json.dumps(seed["items"]),
                        is_seed=True,
                    )
                )
            db.commit()
    finally:
        db.close()
    jobs_module.recover_orphaned_jobs()
    yield
    jobs_module.shutdown_executor()


app = FastAPI(title="CCR Platform", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- helpers
def _construct_out(c: Construct) -> ConstructOut:
    return ConstructOut(
        id=c.id,
        name=c.name,
        description=c.description,
        reference=c.reference,
        items=json.loads(c.items_json),
        is_seed=c.is_seed,
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
    return AVAILABLE_MODELS


# --------------------------------------------------------------- projects
@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@app.post("/api/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(name=body.name.strip(), description=body.description.strip())
    db.add(project)
    db.commit()
    return project


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
async def upload_corpus(project_id: str, file: UploadFile, db: Session = Depends(get_db)):
    _get_or_404(db, Project, project_id)

    suffix = Path(file.filename or "upload.csv").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Use CSV or XLSX.")

    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File exceeds the 25 MB upload limit.")

    corpus = Corpus(
        project_id=project_id, filename=file.filename, path="", n_rows=0, columns_json="[]"
    )
    dest = DATA_DIR / "corpora" / f"{corpus.id}{suffix}"
    dest.write_bytes(payload)
    corpus.path = str(dest)

    try:
        df, parse_info = load_corpus(str(dest))
    except IngestError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc

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
    construct = Construct(
        name=body.name.strip(),
        description=body.description.strip(),
        reference=body.reference.strip(),
        items_json=json.dumps(items),
        is_seed=False,
    )
    db.add(construct)
    db.commit()
    return _construct_out(construct)


# -------------------------------------------------------------------- jobs
@app.post("/api/jobs", response_model=JobOut, status_code=201)
def create_job(body: JobCreate, db: Session = Depends(get_db)):
    _get_or_404(db, Project, body.project_id)
    corpus = _get_or_404(db, Corpus, body.corpus_id)
    _get_or_404(db, Construct, body.construct_id)

    if body.text_column not in json.loads(corpus.columns_json):
        raise HTTPException(400, f"Column '{body.text_column}' not in corpus columns.")
    allowed = {m["name"] for m in AVAILABLE_MODELS} | {FAKE_MODEL_NAME}
    if body.model_name not in allowed:
        raise HTTPException(400, f"Unknown model '{body.model_name}'.")

    job = Job(
        project_id=body.project_id,
        corpus_id=body.corpus_id,
        construct_id=body.construct_id,
        text_column=body.text_column,
        model_name=body.model_name,
    )
    db.add(job)
    db.commit()
    jobs_module.submit_job(job.id)
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
    return FileResponse(
        job.result_path, media_type="text/csv", filename=f"ccr_results_{job_id[:8]}.csv"
    )


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


# ------------------------------------------------------------ static (SPA)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
