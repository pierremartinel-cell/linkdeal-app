FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r backend/requirements.txt

WORKDIR /app/backend
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
