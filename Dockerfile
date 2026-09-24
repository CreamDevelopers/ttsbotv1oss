FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Tokyo

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libopus0 tzdata && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 bot && \
    mkdir -p /app/data && \
    chown -R bot:bot /app/data
USER bot

CMD ["python", "main.py"]
