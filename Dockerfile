FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=parchment.settings.prod

WORKDIR /app

ARG REQUIREMENTS=requirements.txt
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r ${REQUIREMENTS}

# Bake the embedding model into the image so workers don't download it at runtime.
# If the download fails the build continues, and generation falls back to TF-IDF.
ENV HF_HOME=/opt/huggingface
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')" \
    || echo "WARNING: could not download ${EMBEDDING_MODEL}; the TF-IDF fallback will be used"

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/media /app/staticfiles "$HF_HOME" \
    && chown -R app:app /app "$HF_HOME"

COPY --chown=app:app . .
RUN chmod +x docker/entrypoint.sh

USER app

EXPOSE 8000

ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["gunicorn", "parchment.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
