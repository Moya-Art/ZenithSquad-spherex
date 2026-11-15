# Phase 5 API image. Not deployed here: Cloud Run, Artifact Registry and the Vercel origin are
# Phase 8's job. The interpreter is the same 3.14 the local venv was frozen from, so the container
# cannot fail where local work passed.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline ./pipeline
COPY api ./api
COPY data/targets.json ./data/targets.json

# The container filesystem is ephemeral, so every cold start begins with an empty cache and pays for
# a cold /frames build. Phase 8 points these two variables at a bucket instead.
ENV API_CACHE_DIR=/tmp/api-cache \
    FITS_CACHE_DIR=/tmp/fits-cache

EXPOSE 8080

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
