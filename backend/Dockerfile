# API service (Cloud Run). No PDAL here: LiDAR runs in the worker image.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[gcp]"
ENV PORT=8000
CMD exec uvicorn tr_api.main:app --host 0.0.0.0 --port ${PORT}
