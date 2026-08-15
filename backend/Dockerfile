FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn requests python-multipart jinja2 aiofiles pywebpush tzdata

COPY backend /app/backend

ENV TZ=Europe/Rome
ENV TIMEZONE=Europe/Rome
ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
