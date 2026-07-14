"""File storage behind one interface: local disk (default) or S3-compatible.

Production-ready now, enabled by configuration at deploy time (Deva,
2026-07-13): the R2/S3 code path ships with the codebase so flipping a
production instance to object storage is an env change, never a development
task. Local dev keeps writing plain files under CCR_DATA_DIR.

Locator scheme (stored in the DB's existing path columns - no migration):
  * local backend: an absolute filesystem path (exactly as before);
  * s3 backend:    "s3://{key}" inside the configured bucket.
Old rows with absolute paths keep working even on an s3-configured instance.

Config (s3 backend): CCR_STORAGE=s3, CCR_S3_ENDPOINT (R2: the account
endpoint URL), CCR_S3_BUCKET, CCR_S3_ACCESS_KEY_ID, CCR_S3_SECRET_ACCESS_KEY.
The bucket stays private; downloads stream through the API, so no public
access or presigned-URL exposure is required.

Embedding caches deliberately stay on local disk: they are derived data,
cheap to recompute, and read with numpy - a cache does not need durability.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .db import DATA_DIR

S3_PREFIX = "s3://"

_client = None  # injectable for tests


def backend() -> str:
    return os.environ.get("CCR_STORAGE", "local").lower()


def _s3():
    global _client
    if _client is None:
        import boto3  # lazy: only s3-configured deployments need it

        _client = boto3.client(
            "s3",
            endpoint_url=os.environ["CCR_S3_ENDPOINT"],
            aws_access_key_id=os.environ["CCR_S3_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["CCR_S3_SECRET_ACCESS_KEY"],
            region_name=os.environ.get("CCR_S3_REGION", "auto"),
        )
    return _client


def _bucket() -> str:
    return os.environ["CCR_S3_BUCKET"]


def is_s3(locator: str) -> bool:
    return locator.startswith(S3_PREFIX)


# ------------------------------------------------------------------ write
def store_bytes(category: str, name: str, data: bytes) -> str:
    """Persist bytes under category/name; return the locator to store in the DB."""
    key = f"{category}/{name}"
    if backend() == "s3":
        _s3().put_object(Bucket=_bucket(), Key=key, Body=data)
        return S3_PREFIX + key
    dest = DATA_DIR / category / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return str(dest)


def store_file(category: str, name: str, src: Path) -> str:
    return store_bytes(category, name, Path(src).read_bytes())


# ------------------------------------------------------------------- read
def exists(locator: str) -> bool:
    if not locator:
        return False
    if is_s3(locator):
        try:
            _s3().head_object(Bucket=_bucket(), Key=locator[len(S3_PREFIX):])
            return True
        except Exception:
            return False
    return Path(locator).exists()


def fetch_to_local(locator: str) -> tuple[Path, bool]:
    """Return (local_path, is_temporary). Caller unlinks temporary files
    after use; local-backend paths are returned as-is."""
    if is_s3(locator):
        key = locator[len(S3_PREFIX):]
        suffix = Path(key).suffix or ".bin"
        fd, tmp = tempfile.mkstemp(suffix=suffix, prefix="ccr_s3_")
        os.close(fd)
        _s3().download_file(_bucket(), key, tmp)
        return Path(tmp), True
    return Path(locator), False


def open_stream(locator: str):
    """Iterator of byte chunks, for streaming downloads through the API."""
    if is_s3(locator):
        body = _s3().get_object(Bucket=_bucket(), Key=locator[len(S3_PREFIX):])["Body"]
        return iter(lambda: body.read(64 * 1024), b"")
    fh = open(locator, "rb")

    def gen():
        with fh:
            while chunk := fh.read(64 * 1024):
                yield chunk

    return gen()


# ------------------------------------------------------------------ delete
def delete(locator: str) -> None:
    if not locator:
        return
    if is_s3(locator):
        try:
            _s3().delete_object(Bucket=_bucket(), Key=locator[len(S3_PREFIX):])
        except Exception:
            pass  # deletion is best-effort; the TTL sweep retries implicitly
        return
    Path(locator).unlink(missing_ok=True)


def move_local_into_storage(category: str, name: str, local_path: Path) -> str:
    """Store a locally produced file; the source copy is removed unless it IS
    the stored destination (local backend writing in place)."""
    locator = store_file(category, name, local_path)
    src = Path(local_path)
    if is_s3(locator) or (src.exists() and str(src.resolve()) != str(Path(locator).resolve())):
        src.unlink(missing_ok=True)
    return locator
