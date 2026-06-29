FROM python:3.12-slim

# Зависимости для сборки telegram-bot-api + ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    wget \
    libssl-dev \
    zlib1g-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Скачиваем готовый бинарник telegram-bot-api
RUN wget -q https://github.com/tdlib/telegram-bot-api/releases/download/v7.3/telegram-bot-api-amd64-linux -O /usr/local/bin/telegram-bot-api \
    && chmod +x /usr/local/bin/telegram-bot-api

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV WORK_DIR=/tmp/convertbot
ENV LOCAL_API_DIR=/tmp/tgapi

RUN mkdir -p /tmp/convertbot /tmp/tgapi

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
