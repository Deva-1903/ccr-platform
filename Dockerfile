# CCR Platform - single-container deployment (one deployable unit: FastAPI
# serves both the JSON API and the prebuilt React SPA from backend/static).
#
# Build:            docker build -t ccr-platform .
# Ephemeral demo:   docker run -p 7860:7860 ccr-platform
# Persistent:       docker run -p 7860:7860 \
#                     -e CCR_SESSION_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))") \
#                     -e CCR_DATA_DIR=/data -e CCR_COOKIE_SECURE=1 \
#                     -v ccr_data:/data ccr-platform
#
# NOTE: run `npm run build` in frontend/ before building the image - the
# committed backend/static is what ships (no Node stage; keeps HF Spaces
# builds fast and the image small).

FROM python:3.11-slim

# Defaults favor a hosted instance: retention purge on, model pre-warmed.
# Data dir defaults to /tmp so the container runs under any UID (HF Spaces);
# persistent deployments override CCR_DATA_DIR to a mounted volume.
ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf-cache \
    CCR_DATA_DIR=/tmp/ccr-data \
    CCR_ANON_TTL_HOURS=24 \
    CCR_WARM_MODEL=1

WORKDIR /srv

# CPU-only torch FIRST: this Space runs on cpu-basic, but the default PyPI
# torch drags in the multi-GB CUDA wheel stack, which bloats the image and
# OOM-kills the builder at the model-bake step below (observed 2026-07-17).
# With torch already satisfied, the requirements install skips it entirely.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the DEFAULT model (MiniLM, ~90 MB - the CCR reference model) into the
# image so the first run never stalls on a download. The E5 models are large
# (1+ GB) and lazy-load into HF_HOME on first use instead; the dir stays
# writable for any runtime UID.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" \
    && chmod -R 777 /opt/hf-cache

COPY backend/app ./app
COPY backend/static ./static
# registry.py/construct_lib.py resolve packages/ two levels above app/
# (= "/" here), so /packages is exactly where they look.
COPY packages /packages
# Synthetic demo corpora served at /samples for the tester guide (/guide);
# resolved the same way as packages/.
COPY sample_data /sample_data

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
