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

user_queues: dict[int, asyncio.Queue] = {}
user_tasks: dict[int, asyncio.Task] = {}

# ---------- CONVERT ----------
def convert(src: Path, dst: Path):
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(src),
                "-map", "0:v:0",
                "-map", "0:a?",
                "-c:v", "copy",
                "-c:a", "aac",
                "-ac", "2",
                "-b:a", "128k",
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

# ---------- PROCESS ONE FILE ----------
async def process_file(client: Client, message: Message, index: int, total: int):
    doc = message.document
    name = doc.file_name or "file.mts"
    prefix = f"[{index}/{total}] " if total > 1 else ""

    msg = await message.reply_text(f"{prefix}📥 Получаю файл...")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / name
        dst = td / (Path(name).stem + ".mp4")

        try:
            await client.download_media(
                message,
                file_name=str(src),
                progress=progress,
                progress_args=(msg, f"{prefix}⬇️ Скачиваю..."),
            )
        except Exception as e:
            await msg.edit_text(f"{prefix}❌ Ошибка скачивания:\n{e}")
            return

        await msg.edit_text(f"{prefix}⚙️ Конвертирую...")
        loop = asyncio.get_event_loop()
        ok, err = await loop.run_in_executor(None, convert, src, dst)

        if not ok:
            await msg.edit_text(f"{prefix}❌ Ошибка ffmpeg:\n{err}")
            return

        size_mb = dst.stat().st_size / 1024 / 1024
        await msg.edit_text(f"{prefix}📤 Отправляю MP4 ({size_mb:.1f} МБ)...")

        for attempt in range(5):
            try:
                await client.send_document(
                    chat_id=message.chat.id,
                    document=str(dst),
                    file_name=dst.name,
                    caption=f"✅ Готово {prefix}",
                    progress=progress,
                    progress_args=(msg, f"{prefix}📤 Отправляю..."),
                )
                await msg.delete()
                break
            except FloodWait as e:
                wait = e.value + 2
                await msg.edit_text(f"{prefix}⏳ Подождите {wait} сек...")
                await asyncio.sleep(wait)
            except Exception as e:
                await msg.edit_text(f"{prefix}❌ Ошибка отправки:\n{e}")
                break

# ---------- QUEUE WORKER ----------
async def queue_worker(client: Client, chat_id: int):
    queue = user_queues[chat_id]
    while True:
        try:
            message, index, total = await asyncio.wait_for(queue.get(), timeout=60)
            await process_file(client, message, index, total)
            queue.task_done()
        except asyncio.TimeoutError:
            break
        except Exception as e:
            log.error(f"Worker error: {e}")
            continue
    del user_queues[chat_id]
    del user_tasks[chat_id]

# ---------- START ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text(
        "📩 Отправь до 10 .MTS файлов как документы — я конвертирую их в MP4 по очереди"
    )

# ---------- HANDLER ----------
@app.on_message(filters.document)
async def handle(client: Client, message: Message):
    doc = message.document
    name = doc.file_name or ""
    if not name.lower().endswith(".mts"):
        await message.reply_text("❌ Только .MTS файлы")
        return

    chat_id = message.chat.id

    if chat_id not in user_queues:
        user_queues[chat_id] = asyncio.Queue(maxsize=10)

    queue = user_queues[chat_id]

    if queue.full():
        await message.reply_text("❌ Очередь полна — максимум 10 файлов за раз")
        return

    pos = queue.qsize() + 1
    await queue.put((message, pos, pos))
    await message.reply_text(f"✅ Файл добавлен в очередь — позиция {pos}")

    if chat_id not in user_tasks or user_tasks[chat_id].done():
        user_tasks[chat_id] = asyncio.create_task(queue_worker(client, chat_id))

# ---------- MAIN ----------
if __name__ == "__main__":
    log.info("Bot started")
    app.run()
