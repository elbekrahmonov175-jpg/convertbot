#!/bin/bash
set -e

echo "==> Запуск Local Telegram Bot API Server..."
telegram-bot-api \
    --api-id="$TELEGRAM_API_ID" \
    --api-hash="$TELEGRAM_API_HASH" \
    --local \
    --dir="$LOCAL_API_DIR" \
    --http-port=8081 \
    --log=/tmp/tgapi.log \
    &

echo "==> Ждём запуска Local API (5 сек)..."
sleep 5

echo "==> Запуск бота..."
exec python bot.py
