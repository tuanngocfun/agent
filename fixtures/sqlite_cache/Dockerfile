ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

LABEL org.kube-repair.fixture="sqlite-cache-v1"
WORKDIR /app
COPY app.py /app/app.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CACHE_DIR=/var/lib/repair-sqlite FIXTURE_REQUIRES_ROOT=0
USER 0:0
ENTRYPOINT ["python", "/app/app.py"]
