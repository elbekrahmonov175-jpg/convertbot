#!/bin/bash
set -e

echo "==> Starting Local Telegram Bot API Server..."
telegram-bot-api \
    --api-id="$TELEGRAM_API_ID" \
    --api-hash="$TELEGRAM_API_HASH" \
    --local \
    --dir="$LOCAL_API_DIR" \
    --http-port=8081 \
    --log=/tmp/tgapi.log \
    &

echo "==> Waiting for Local API (5 sec)..."
sleep 5

echo "==> Starting bot..."
exec python bot.py
