# Looked Up live layer: Hugging Face Space (Docker SDK) or any container host. Boots in seconds, < 200 MB RAM.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lookedup_live ./lookedup_live
ENV LIVE_STATE_DIR=/tmp/looked-up-live PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["uvicorn", "lookedup_live.app:app", "--host", "0.0.0.0", "--port", "7860"]
