#!/usr/bin/env python3
import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

app = Client("convertbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------- CONVERT ----------
def convert(src: Path, dst: Path):
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(src),
                "-c:v", "libx264",
                "-crf", "32",
                "-preset", "ultrafast",
                "-tune", "fastdecode",
                "-vf", "scale=1280:-2",
                "-c:a", "aac",
                "-b:a", "96k",
                "-threads", "0",
                str(dst)
            ],
            capture_output=True,
            text=True,
            timeout=3600
        )
        return result.returncode == 0, result.stderr[-400:]
    except subprocess.TimeoutExpired:
        return False, "Timeout ffmpeg"

# ---------- START ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text("📩 Отправь .MTS файл как документ — я конвертирую в MP4")

# ---------- HANDLER ----------
@app.on_message(filters.document)
async def handle(client: Client, message: Message):
    doc = message.document
    name = doc.file_name or ""
    if not name.lower().endswith(".mts"):
        await message.reply_text("❌ Только .MTS файлы")
        return

    msg = await message.reply_text("📥 Получаю файл...")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / name
        dst = td / (Path(name).stem + ".mp4")

        try:
            await msg.edit_text("⬇️ Скачиваю файл...")
            await client.download_media(message, file_name=str(src))
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
        try:
            await client.send_document(
                chat_id=message.chat.id,
                document=str(dst),
                file_name=dst.name,
                caption="✅ Готово"
            )
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка отправки:\n{e}")

# ---------- MAIN ----------
if __name__ == "__main__":
    log.info("Bot started")
    app.run()
