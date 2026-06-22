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

API_ID   = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")   # userbot

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ----- БОТ (отправка / команды) -----
bot = Client(
    "convertbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp",
    max_concurrent_transmissions=1,
    sleep_threshold=60,
)

# ----- USERBOT (скачивание больших файлов) -----
# Если SESSION_STRING не задан — скачивает бот (работает только для файлов <2 ГБ без обрывов)
user = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    max_concurrent_transmissions=1,
    sleep_threshold=120,
) if SESSION_STRING else None

user_queues: dict[int, asyncio.Queue] = {}
user_tasks:  dict[int, asyncio.Task]  = {}

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
                "-profile:v", "baseline",
                "-level", "3.1",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-ac", "2",
                "-b:a", "128k",
                "-movflags", "+faststart",
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
_PROGRESS_INTERVAL = 4.0

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
        log.warning(f"FloodWait {e.value}s в progress, жду {wait}s...")
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

# ---------- СКАЧИВАНИЕ ЧЕРЕЗ USERBOT ----------
async def download_via_userbot(message: Message, src: Path, msg, prefix: str) -> bool:
    """
    Скачивает файл через userbot-клиент.
    message — оригинальное сообщение из чата (от бота).
    Userbot должен быть участником того же чата.
    """
    downloader = user  # userbot-клиент

    for attempt in range(5):
        try:
            await safe_edit(msg, f"{prefix}⬇️ Скачиваю через userbot... (попытка {attempt + 1}/5)")
            if src.exists():
                src.unlink()

            # Получаем то же сообщение через userbot по chat_id + message_id
            target_msg = await downloader.get_messages(
                chat_id=message.chat.id,
                message_ids=message.id
            )
            if not target_msg or not target_msg.document:
                log.warning(f"Userbot не нашёл сообщение (попытка {attempt + 1}/5)")
                await asyncio.sleep(5)
                continue

            await downloader.download_media(
                target_msg,
                file_name=str(src),
                progress=progress,
                progress_args=(msg, f"{prefix}⬇️ Скачиваю..."),
            )

            if src.exists() and src.stat().st_size > 0:
                size_mb = src.stat().st_size / 1024 / 1024
                log.info(f"Файл скачан через userbot: {size_mb:.1f} МБ")
                return True
            else:
                log.warning(f"Userbot: файл не скачался (попытка {attempt + 1}/5)")
                await asyncio.sleep(5)

        except FloodWait as e:
            wait = e.value + 5
            log.warning(f"FloodWait {e.value}s при скачивании userbot, жду {wait}s...")
            await asyncio.sleep(wait)
        except Exception as e:
            log.warning(f"Userbot ошибка скачивания (попытка {attempt + 1}/5): {e}")
            if attempt < 4:
                await asyncio.sleep(5)

    return False

# ---------- СКАЧИВАНИЕ ЧЕРЕЗ БОТА (fallback) ----------
async def download_via_bot(message: Message, src: Path, msg, prefix: str) -> bool:
    for attempt in range(5):
        try:
            await safe_edit(msg, f"{prefix}⬇️ Скачиваю... (попытка {attempt + 1}/5)")
            if src.exists():
                src.unlink()

            await bot.download_media(
                message,
                file_name=str(src),
                progress=progress,
                progress_args=(msg, f"{prefix}⬇️ Скачиваю..."),
            )

            if src.exists() and src.stat().st_size > 0:
                return True
            else:
                log.warning(f"Бот: файл не скачался (попытка {attempt + 1}/5)")
                await asyncio.sleep(5)

        except FloodWait as e:
            wait = e.value + 5
            log.warning(f"FloodWait {e.value}s при скачивании бот, жду {wait}s...")
            await asyncio.sleep(wait)
        except Exception as e:
            log.warning(f"Бот ошибка скачивания (попытка {attempt + 1}/5): {e}")
            if attempt < 4:
                await asyncio.sleep(5)

    return False

# ---------- PROCESS ONE FILE ----------
async def process_file(message: Message, index: int, total: int):
    doc = message.document
    name = doc.file_name or "file.mts"
    prefix = f"[{index}/{total}] " if total > 1 else ""

    msg = await safe_reply(message, f"{prefix}📥 Получаю файл...")
    if not msg:
        return

    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        src = td / name
        dst = td / (Path(name).stem + ".mp4")

        # Скачиваем через userbot если доступен, иначе через бота
        if user:
            downloaded = await download_via_userbot(message, src, msg, prefix)
            if not downloaded:
                await safe_edit(msg, f"{prefix}⚠️ Userbot не справился, пробую через бота...")
                downloaded = await download_via_bot(message, src, msg, prefix)
        else:
            downloaded = await download_via_bot(message, src, msg, prefix)

        if not downloaded:
            await safe_edit(msg, f"{prefix}❌ Не удалось скачать файл")
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
                wait = e.value + random.randint(1, 5)
                log.warning(f"FloodWait {e.value}s на send_document (attempt {attempt + 1}/10), жду {wait}s...")
                await safe_edit(msg, f"{prefix}⏳ Подождите {wait} сек...")
                await asyncio.sleep(wait)
            except Exception as e:
                await safe_edit(msg, f"{prefix}❌ Ошибка отправки:\n{e}")
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
        except FloodWait as e:
            wait = e.value + random.randint(1, 5)
            log.warning(f"FloodWait {e.value}s в queue_worker (chat_id={chat_id}), жду {wait}s...")
            await asyncio.sleep(wait)
        except Exception as e:
            log.error(f"Worker error: {e}", exc_info=True)
        finally:
            queue.task_done()

        await asyncio.sleep(2.0)

    if chat_id in user_queues:
        del user_queues[chat_id]
    if chat_id in user_tasks:
        del user_tasks[chat_id]

# ---------- START ----------
@bot.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    mode = "userbot (большие файлы ✅)" if user else "бот (до ~1 ГБ)"
    await safe_reply(message,
        f"📩 Отправь до 10 .MTS файлов как документы — конвертирую в MP4 по очереди\n"
        f"🔧 Режим скачивания: {mode}"
    )

# ---------- HANDLER ----------
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
        await safe_reply(message, "❌ Очередь полна — максимум 10 файлов за раз")
        return

    pos = queue.qsize() + 1
    await queue.put((message, pos, pos))
    await safe_reply(message, f"✅ Файл добавлен в очередь — позиция {pos}")

    if chat_id not in user_tasks or user_tasks[chat_id].done():
        user_tasks[chat_id] = asyncio.create_task(queue_worker(chat_id))

# ---------- MAIN ----------
async def main():
    log.info("Bot started")

    if user:
        log.info("Запускаю userbot...")
        await user.start()
        me = await user.get_me()
        log.info(f"Userbot авторизован как: {me.first_name} (@{me.username})")
    else:
        log.warning("SESSION_STRING не задан — скачивание только через бота")

    await bot.start()
    log.info("Бот запущен, жду сообщений...")
    await asyncio.Event().wait()  # держим процесс

if __name__ == "__main__":
    asyncio.run(main())
