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

API_ID    = int(os.environ.get("API_ID", "0"))
API_HASH  = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

bot = Client(
    "convertbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp",
    sleep_threshold=60,
)

user_queues: dict[int, asyncio.Queue] = {}
user_tasks:  dict[int, asyncio.Task]  = {}

# ---------- CONVERT ----------
def convert(src: Path, dst: Path):
    try:
        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", str(src),
            "-map", "0:v:0",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-profile:v", "baseline",
            "-level", "3.1",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-ac", "2",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(dst)
        ], capture_output=True, text=True, timeout=3600)
        return result.returncode == 0, result.stderr[-400:]
    except subprocess.TimeoutExpired:
        return False, "Timeout ffmpeg"

# ---------- PROGRESS ----------
_last: dict[int, float] = {}

async def progress(current, total, msg, action):
    now = time.monotonic()
    if now - _last.get(msg.id, 0) < 4.0 and current < total:
        return
    _last[msg.id] = now
    pct = int(current * 100 / total) if total else 0
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    try:
        await msg.edit_text(f"{action}\n{bar} {pct}%\n{current/1024/1024:.1f} / {total/1024/1024:.1f} МБ")
    except Exception:
        pass

# ---------- SAFE HELPERS ----------
async def safe_reply(message: Message, text: str):
    for _ in range(5):
        try:
            return await message.reply_text(text)
        except FloodWait as e:
            await asyncio.sleep(e.value + 3)
        except Exception as e:
            log.error(f"reply error: {e}")
            return None

async def safe_edit(msg, text: str):
    for _ in range(5):
        try:
            return await msg.edit_text(text)
        except FloodWait as e:
            await asyncio.sleep(e.value + 3)
        except Exception:
            return None

# ---------- PROCESS ----------
async def process_file(message: Message, index: int, total: int):
    doc = message.document
    name = (doc.file_name if doc else None) or "file.mts"
    prefix = f"[{index}/{total}] " if total > 1 else ""

    msg = await safe_reply(message, f"{prefix}📥 Скачиваю...")
    if not msg:
        return

    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        src = td / name
        dst = td / (Path(name).stem + ".mp4")

        try:
            await bot.download_media(
                message,
                file_name=str(src),
                progress=progress,
                progress_args=(msg, f"{prefix}⬇️ Скачиваю..."),
            )
        except Exception as e:
            await safe_edit(msg, f"{prefix}❌ Ошибка скачивания: {e}")
            return

        if not src.exists() or src.stat().st_size == 0:
            await safe_edit(msg, f"{prefix}❌ Файл не скачался")
            return

        await safe_edit(msg, f"{prefix}⚙️ Конвертирую...")
        ok, err = await asyncio.get_event_loop().run_in_executor(None, convert, src, dst)

        if not ok:
            await safe_edit(msg, f"{prefix}❌ Ошибка ffmpeg:\n{err}")
            return

        out_mb = dst.stat().st_size / 1024 / 1024
        await safe_edit(msg, f"{prefix}📤 Отправляю MP4 ({out_mb:.1f} МБ)...")

        for attempt in range(10):
            try:
                await bot.send_document(
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
                await asyncio.sleep(e.value + random.randint(1, 5))
            except Exception as e:
                await safe_edit(msg, f"{prefix}❌ Ошибка отправки: {e}")
                break

# ---------- QUEUE WORKER ----------
async def queue_worker(chat_id: int):
    queue = user_queues[chat_id]
    while True:
        try:
            message, index, total = await asyncio.wait_for(queue.get(), timeout=60)
        except asyncio.TimeoutError:
            break
        try:
            await process_file(message, index, total)
        except Exception as e:
            log.error(f"Worker error: {e}", exc_info=True)
        finally:
            queue.task_done()
        await asyncio.sleep(2.0)
    user_queues.pop(chat_id, None)
    user_tasks.pop(chat_id, None)

# ---------- HANDLERS ----------
@bot.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await safe_reply(message, "📩 Отправь .MTS файлы как документы — конвертирую в MP4")

@bot.on_message(filters.document)
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
        await safe_reply(message, "❌ Очередь полна")
        return

    pos = queue.qsize() + 1
    await queue.put((message, pos, pos))
    await safe_reply(message, f"✅ Файл добавлен в очередь — позиция {pos}")

    if chat_id not in user_tasks or user_tasks[chat_id].done():
        user_tasks[chat_id] = asyncio.create_task(queue_worker(chat_id))

# ---------- MAIN ----------
async def main():
    log.info("Bot started")
    await bot.start()
    log.info("Бот запущен, жду сообщений...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
