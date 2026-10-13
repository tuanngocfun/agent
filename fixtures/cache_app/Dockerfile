ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

LABEL org.kube-repair.fixture="cache-app-v1"
WORKDIR /app
COPY app.py /app/app.py
RUN mkdir -p /var/cache/repair-app /cache && chmod 0755 /var/cache/repair-app && chgrp 2000 /cache && chmod 0770 /cache
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CACHE_DIR=/var/cache/repair-app FIXTURE_REQUIRES_ROOT=0
USER 0:0
ENTRYPOINT ["python", "/app/app.py"]
