# Reproducible runtime for the POI eval backend (server.py + tools/).
#
# Scope: the standard-library + Pillow backend and the stdlib-only tools. This
# image does NOT contain FastVLM / torch or the macOS Swift/MapKit toolchain —
# those run in a separate venv / on the host by design (see
# docs/reproducible-runtime.md). Keeping them out is what makes this image small,
# deterministic, and CI-friendly, and it matches the import-isolation contract
# enforced by tools/check_import_isolation.py.
#
# Pin is by tag here; for a hard supply-chain pin, replace the base tag with its
# @sha256 digest and regenerate requirements.lock with --generate-hashes.
FROM python:3.11.9-slim-bookworm

# Deterministic Python behaviour; no stray .pyc, no pip version chatter.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency layer: copy only the lock so the layer caches on the pin, not on
# source edits. Install the exact pinned set, not the loose requirements.txt.
COPY requirements.lock ./requirements.lock
RUN python3 -m pip install --no-cache-dir -r requirements.lock

# Application: the eval backend + stdlib tools. Datasets and run snapshots are
# never baked in — they mount at runtime under /app/poi-data (see .dockerignore).
COPY server.py ./server.py
COPY validate_upload_package.py ./validate_upload_package.py
COPY tools ./tools
COPY eval ./eval

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 poi
USER poi

# server.py binds 0.0.0.0 inside the container, which it treats as non-local and
# therefore REQUIRES POI_API_TOKEN to be set (fail-loud). Provide it at runtime:
#   docker run -e POI_API_TOKEN=... -e POI_BIND=0.0.0.0 -p 8420:8420 poi-eval
ENV POI_PORT=8420
EXPOSE 8420

CMD ["python3", "server.py"]
