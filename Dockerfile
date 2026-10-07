FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS frontend
WORKDIR /frontend
RUN npm install --global npm@11.6.2
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATA_DIR=/data MODEL_DIR=/opt/models/bge MODEL_CPU_THREADS=2 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
WORKDIR /app
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir torch==2.9.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt -c requirements.lock.txt
COPY model-spec.json ./
COPY scripts/download_model.py ./scripts/download_model.py
RUN python scripts/download_model.py --destination /opt/models/bge
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY --from=frontend /frontend/dist ./frontend/dist/
RUN useradd --uid 10001 --create-home appuser \
    && mkdir -p /data/db /data/uploads /data/tmp /data/quarantine \
    && chown -R appuser:appuser /data
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
