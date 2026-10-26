# Portable alternative to render.yaml. Build: docker build -t hr-policy-agent .
# Run:   docker run -p 10000:10000 --env-file .env hr-policy-agent
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Keyless index baked into the image; a Gemini index can be added at runtime with the key.
RUN python -m app.rag.ingest --embedder tfidf \
    && useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 10000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
