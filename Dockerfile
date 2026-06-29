FROM aiogram/telegram-bot-api:latest AS tgapi

FROM python:3.12-slim

COPY --from=tgapi /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-bot-api

RUN apt-get update && apt-get install -y \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

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
