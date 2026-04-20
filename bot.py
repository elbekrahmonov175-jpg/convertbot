#!/usr/bin/env python3
import asyncio
import logging
import os
import random
import subprocess
import tempfile
import time
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
_progress_last_update: dict[int, float] = {}
_PROGRESS_INTERVAL = 3.0  # seconds between progress edits

async def progress(current, total, msg, action):
    msg_id = msg.id
    now = time.monotonic()
    last = _progress_last_update.get(msg_id, 0.0)
    if now - last < _PROGRESS_INTERVAL and current < total:
        return
    _progress_last_update[msg_id] = now

    pct = int(current * 100 / total)
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    mb_cur = current / 1024 / 1024
    mb_tot = total / 1024 / 1024
    try:
        await msg.edit_text(f"{action}\n{bar} {pct}%\n{mb_cur:.1f} / {mb_tot:.1f} МБ")
        await asyncio.sleep(0.5)
    except FloodWait as e:
        wait = e.value + random.randint(1, 5)
        log.warning(f"FloodWait {e.value}s в progress (msg_id={msg_id}), жду {wait}s...")
        _progress_last_update[msg_id] = now + wait
        await asyncio.sleep(wait)
    except Exception:
        pass

# ---------- SAFE REPLY ----------
async def safe_reply(message: Message, text: str):
    for attempt in range(10):
        try:
            return await message.reply_text(text)
        except FloodWait as e:
            wait = e.value + random.randint(1, 5)
            log.warning(f"FloodWait {e.value}s на reply (attempt {attempt + 1}/10), жду {wait}s...")
            await asyncio.sleep(wait)
        except Exception as e:
            log.error(f"Ошибка reply: {e}")
            return None

# ---------- SAFE EDIT ----------
async def safe_edit(msg, text: str):
    for attempt in range(10):
        try:
            result = await msg.edit_text(text)
            await asyncio.sleep(1.0)
            return result
        except FloodWait as e:
            wait = e.value + random.randint(1, 5)
            log.warning(f"FloodWait {e.value}s на edit (attempt {attempt + 1}/10), жду {wait}s...")
            await asyncio.sleep(wait)
        except Exception:
            return None

# ---------- PROCESS ONE FILE ----------
async def process_file(client: Client, message: Message, index: int, total: int):
    doc = message.document
    name = doc.file_name or "file.mts"
    prefix = f"[{index}/{total}] " if total > 1 else ""

    msg = await safe_reply(message, f"{prefix}📥 Получаю файл...")
    if not msg:
        return

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
            await safe_edit(msg, f"{prefix}❌ Ошибка скачивания:\n{e}")
            return

        await asyncio.sleep(1.5)
        await safe_edit(msg, f"{prefix}⚙️ Конвертирую...")
        loop = asyncio.get_event_loop()
        ok, err = await loop.run_in_executor(None, convert, src, dst)

        if not ok:
            await safe_edit(msg, f"{prefix}❌ Ошибка ffmpeg:\n{err}")
            return

        await asyncio.sleep(1.5)
        size_mb = dst.stat().st_size / 1024 / 1024
        await safe_edit(msg, f"{prefix}📤 Отправляю MP4 ({size_mb:.1f} МБ)...")

        for attempt in range(10):
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
                wait = e.value + random.randint(1, 5)
                log.warning(f"FloodWait {e.value}s на send_document (attempt {attempt + 1}/10), жду {wait}s...")
                await safe_edit(msg, f"{prefix}⏳ Подождите {wait} сек...")
                await asyncio.sleep(wait)
            except Exception as e:
                await safe_edit(msg, f"{prefix}❌ Ошибка отправки:\n{e}")
                break

# ---------- QUEUE WORKER ----------
async def queue_worker(client: Client, chat_id: int):
    queue = user_queues[chat_id]
    while True:
        try:
            message, index, total = await asyncio.wait_for(queue.get(), timeout=60)
            await process_file(client, message, index, total)
            queue.task_done()
            await asyncio.sleep(2.0)
        except asyncio.TimeoutError:
            break
        except FloodWait as e:
            wait = e.value + random.randint(1, 5)
            log.warning(f"FloodWait {e.value}s в queue_worker (chat_id={chat_id}), жду {wait}s...")
            await asyncio.sleep(wait)
        except Exception as e:
            log.error(f"Worker error: {e}")
            continue
    if chat_id in user_queues:
        del user_queues[chat_id]
    if chat_id in user_tasks:
        del user_tasks[chat_id]

# ---------- START ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await safe_reply(message,
        "📩 Отправь до 10 .MTS файлов как документы — я конвертирую их в MP4 по очереди"
    )

# ---------- HANDLER ----------
@app.on_message(filters.document)
async def handle(client: Client, message: Message):
    doc = message.document
    name = doc.file_name or ""
    if not name.lower().endswith(".mts"):
        await safe_reply(message, "❌ Только .MTS файлы")
        return

    chat_id = message.chat.id

    if chat_id not in user_queues:
        user_queues[chat_id] = asyncio.Queue(maxsize=10)

    queue = user_queues[chat_id]

    if queue.full():
        await safe_reply(message, "❌ Очередь полна — максимум 10 файлов за раз")
        return

    pos = queue.qsize() + 1
    await queue.put((message, pos, pos))
    await safe_reply(message, f"✅ Файл добавлен в очередь — позиция {pos}")

    if chat_id not in user_tasks or user_tasks[chat_id].done():
        user_tasks[chat_id] = asyncio.create_task(queue_worker(client, chat_id))

# ---------- MAIN ----------
if __name__ == "__main__":
    log.info("Bot started")
    app.run()
