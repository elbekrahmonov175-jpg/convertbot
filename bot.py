#!/usr/bin/env python3

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path

import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO
)

log = logging.getLogger(__name__)


# ---------- CONVERT ----------
def convert(src: Path, dst: Path):
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(src),
                "-preset", "ultrafast",
                "-c:v", "libx264",
                "-c:a", "aac",
                str(dst)
            ],
            capture_output=True,
            text=True,
            timeout=3600
        )
        return result.returncode == 0, result.stderr[-400:]
    except subprocess.TimeoutExpired:
        return False, "Timeout ffmpeg"


# ---------- DOWNLOAD (FAST + LARGE FILE SUPPORT) ----------
async def download_file(file_url: str, dest: Path):
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as resp:
            if resp.status != 200:
                raise Exception(f"Download failed: {resp.status}")

            with open(dest, "wb") as f:
                while True:
                    chunk = await resp.content.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)


# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📩 Отправь .MTS файл как документ — я конвертирую в MP4"
    )


# ---------- HANDLER ----------
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    name = doc.file_name or ""

    if not name.lower().endswith(".mts"):
        await update.message.reply_text("❌ Только .MTS файлы")
        return

    msg = await update.message.reply_text("📥 Получаю файл...")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / name
        dst = td / (Path(name).stem + ".mp4")

        try:
            tg_file = await context.bot.get_file(doc.file_id)

            # 🔥 ВАЖНО: используем прямую ссылку
            file_url = tg_file.file_path

            await msg.edit_text("⬇️ Скачиваю файл...")
            await download_file(file_url, src)

        except Exception as e:
            await msg.edit_text(f"❌ Ошибка скачивания:\n{e}")
            return

        await msg.edit_text("⚙️ Конвертирую...")

        loop = asyncio.get_event_loop()
        ok, err = await loop.run_in_executor(None, convert, src, dst)

        if not ok:
            await msg.edit_text(f"❌ Ошибка ffmpeg:\n{err}")
            return

        await msg.edit_text("📤 Отправляю MP4...")

        with open(dst, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=dst.name,
                caption="✅ Готово"
            )

        await msg.delete()


# ---------- FALLBACK ----------
async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📩 Отправь .MTS файл")


# ---------- MAIN ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle))
    app.add_handler(MessageHandler(filters.ALL, fallback))

    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
