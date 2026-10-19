FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --system --uid 10001 ferrum && chown -R ferrum /app
USER 10001

EXPOSE 8001

# Exec form: python is PID 1 and gets SIGTERM directly (see worker/main.py for the drain).
CMD ["python", "-m", "worker.main"]
