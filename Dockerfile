# CCR Platform — Cloud Run / container deployment.
# The embedding model is baked into the image so the first request
# doesn't trigger a ~90 MB download (critical for demo cold starts).

FROM python:3.11-slim

# Data + caches in /tmp so the container runs under any UID
# (Hugging Face Spaces runs containers as a non-root user).
ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf-cache \
    CCR_DATA_DIR=/tmp/ccr-data

WORKDIR /srv

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download ALL offered models into the image layer — a user picking a
# non-default model must not trigger a multi-hundred-MB download mid-job
# (looks like a hang). Make the cache usable by any runtime UID.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    [SentenceTransformer(m) for m in ( \
        'sentence-transformers/all-MiniLM-L6-v2', \
        'sentence-transformers/all-mpnet-base-v2', \
        'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')]" \
    && chmod -R 777 /opt/hf-cache

COPY backend/app ./app
COPY backend/static ./static

# Demo note: SQLite + uploads live on the container's ephemeral disk —
# data resets on restart/redeploy. Acceptable for a demo; use
# Postgres + S3/GCS object storage before any real use.
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
