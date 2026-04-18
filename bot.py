#!/usr/bin/env python3
import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

app = Client(
    "convertbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp",
    max_concurrent_transmissions=4,
)

# ---------- CONVERT ----------
def convert(src: Path, dst: Path):
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(src),
                "-map", "0:v:0",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-crf", "23",
                "-preset", "ultrafast",
                "-c:a", "aac",
                "-ac", "2",
                "-b:a", "128k",
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

# ---------- PROGRESS ----------
async def progress(current, total, msg, action):
    pct = int(current * 100 / total)
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    mb_cur = current / 1024 / 1024
    mb_tot = total / 1024 / 1024
    try:
        await msg.edit_text(f"{action}\n{bar} {pct}%\n{mb_cur:.1f} / {mb_tot:.1f} МБ")
    except Exception:
        pass

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
            await client.download_media(
                message,
                file_name=str(src),
                progress=progress,
                progress_args=(msg, "⬇️ Скачиваю..."),
            )
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка скачивания:\n{e}")
            return

        await msg.edit_text("⚙️ Конвертирую...")
        loop = asyncio.get_event_loop()
        ok, err = await loop.run_in_executor(None, convert, src, dst)

        if not ok:
            await msg.edit_text(f"❌ Ошибка ffmpeg:\n{err}")
            return

        size_mb = dst.stat().st_size / 1024 / 1024
        await msg.edit_text(f"📤 Отправляю MP4 ({size_mb:.1f} МБ)...")

        for attempt in range(5):
            try:
                await client.send_document(
                    chat_id=message.chat.id,
                    document=str(dst),
                    file_name=dst.name,
                    caption="✅ Готово",
                    progress=progress,
                    progress_args=(msg, "📤 Отправляю..."),
                )
                await msg.delete()
                break
            except FloodWait as e:
                wait = e.value + 2
                await msg.edit_text(f"⏳ Telegram просит подождать {wait} сек...")
                await asyncio.sleep(wait)
            except Exception as e:
                await msg.edit_text(f"❌ Ошибка отправки:\n{e}")
                break

# ---------- MAIN ----------
if __name__ == "__main__":
    log.info("Bot started")
    app.run()
