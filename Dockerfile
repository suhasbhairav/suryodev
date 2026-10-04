FROM python:3.11-slim

LABEL org.opencontainers.image.title="Suryodev"
LABEL org.opencontainers.image.description="Turn any website into a narrated product video"
LABEL org.opencontainers.image.url="https://suhasbhairav.com"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libx11-6 \
    libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxfixes3 \
    libxkbcommon0 libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY create_demo.py main.py intro_music_gemini.mp3 ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && playwright install chromium

COPY .env.example ./
RUN mkdir -p output

ENTRYPOINT ["python", "main.py"]
