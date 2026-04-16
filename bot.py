#!/usr/bin/env python3

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# 👉 ВАЖНО: вставь свой токен
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8632611940:AAEMcZqqs6-cXfunzW0aBlJ77BQ6-1QWHo0")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)


def convert(src: Path, dst: Path):
    """Конвертация MTS -> MP4 через ffmpeg"""
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-c:v", "copy", "-c:a", "aac", str(dst)],
        capture_output=True,
        text=True
    )
    return result.returncode == 0, result.stderr[-400:]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправь .MTS файл как документ — я конвертирую в MP4"
    )


async def handle_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    filename = doc.file_name or ""

    if not filename.lower().endswith(".mts"):
        await update.message.reply_text("❌ Нужен файл .MTS")
        return

    msg = await update.message.reply_text(f"⬇️ Скачиваю {filename}...")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src = tmp / filename
        dst = tmp / (Path(filename).stem + ".mp4")

        try:
            file = await context.bot.get_file(doc.file_id)
            await file.download_to_drive(str(src))
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка скачивания: {e}")
            return

        await msg.edit_text("⚙️ Конвертирую...")

        loop = asyncio.get_event_loop()
        ok, err = await loop.run_in_executor(None, convert, src, dst)

        if not ok:
            await msg.edit_text(f"❌ Ошибка ffmpeg:\n{err}")
            return

        await msg.edit_text("📤 Отправляю файл...")

        with open(dst, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=dst.name,
                caption="✅ Готово!"
            )

        await msg.delete()


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправь .MTS файл как документ")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_doc))
    app.add_handler(MessageHandler(filters.ALL, fallback))

    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
