FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY docker-entrypoint.py .
RUN mkdir -p /app/demo /app/template && APP_DB_PATH=/app/template/demo_template.db python -m app.seed && mv /app/template/demo.db /app/template/demo_template.db
EXPOSE 8088
ENTRYPOINT ["python", "docker-entrypoint.py"]
