import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from pyrogram import Client

from converter import convert_mts_to_mp4
from queue_manager import ConversionQueue, JobStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
ALLOWED_USERS_RAW = os.environ.get("ALLOWED_USERS", "")
ALLOWED_USERS = set(
    int(uid.strip()) for uid in ALLOWED_USERS_RAW.split(",") if uid.strip().isdigit()
)

WORK_DIR = Path(os.environ.get("WORK_DIR", "/tmp/convertbot"))
WORK_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE_MB = 2000

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
queue = ConversionQueue(max_workers=2)

# Pyrogram клиент для скачивания больших файлов
pyro = Client(
    "convertbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp",
)


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def format_size(bytes_size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} TB"


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}с"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}м {s}с"
    h, m = divmod(m, 60)
    return f"{h}ч {m}м"


@dp.message(CommandStart())
async def cmd_start(message: Message):
    if not is_allowed(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этому боту.")
        return
    await message.answer(
        "👋 <b>MTS → MP4 Конвертер</b>\n\n"
        "Просто отправь мне <code>.mts</code> или <code>.m2ts</code> файл "
        "и я конвертирую его в MP4.\n\n"
        f"⚠️ <b>Максимальный размер файла:</b> {MAX_FILE_SIZE_MB} MB\n\n"
        "📋 Команды:\n"
        "/status — статус очереди\n"
        "/cancel — отменить текущую задачу"
    )


@dp.message(Command("status"))
async def cmd_status(message: Message):
    if not is_allowed(message.from_user.id):
        return
    stats = queue.get_stats()
    await message.answer(
        f"📊 <b>Статус очереди</b>\n\n"
        f"⏳ В очереди: {stats['queued']}\n"
        f"⚙️ Конвертируется: {stats['processing']}\n"
        f"✅ Завершено (сессия): {stats['done']}\n"
        f"❌ Ошибок (сессия): {stats['failed']}"
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message):
    if not is_allowed(message.from_user.id):
        return
    cancelled = queue.cancel_user_jobs(message.from_user.id)
    if cancelled:
        await message.answer(f"🛑 Отменено задач из очереди: {cancelled}")
    else:
        await message.answer("ℹ️ У вас нет задач в очереди.")


@dp.message(F.document)
async def handle_document(message: Message):
    if not is_allowed(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этому боту.")
        return

    doc = message.document
    filename = doc.file_name or ""
    ext = Path(filename).suffix.lower()

    if ext not in (".mts", ".m2ts"):
        await message.answer(
            "❌ Неверный формат файла.\n"
            "Поддерживаются только <code>.mts</code> и <code>.m2ts</code> файлы."
        )
        return

    file_size_mb = doc.file_size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        await message.answer(
            f"❌ Файл слишком большой: <b>{file_size_mb:.0f} MB</b>\n"
            f"Максимум: <b>{MAX_FILE_SIZE_MB} MB</b>"
        )
        return

    user_jobs = queue.get_user_jobs(message.from_user.id)
    if len(user_jobs) >= 3:
        await message.answer(
            "⚠️ У вас уже 3 задачи в очереди.\n"
            "Дождитесь завершения или используйте /cancel"
        )
        return

    status_msg = await message.answer(
        f"📥 <b>Получен файл:</b> <code>{filename}</code>\n"
        f"📦 Размер: {format_size(doc.file_size)}\n\n"
        "⬇️ Скачиваю файл через MTProto..."
    )

    job_id = str(uuid.uuid4())[:8]
    input_path = WORK_DIR / f"{job_id}_input{ext}"
    output_path = WORK_DIR / f"{job_id}_output.mp4"

    try:
        download_start = time.time()

        # Скачиваем через Pyrogram (без лимита 20MB)
        last_update = [0.0]

        async def progress(current, total):
            now = time.time()
            if now - last_update[0] < 5:
                return
            last_update[0] = now
            pct = current / total * 100 if total else 0
            try:
                await status_msg.edit_text(
                    f"⬇️ <b>Скачиваю файл...</b>\n"
                    f"📦 {format_size(current)} / {format_size(total)} ({pct:.0f}%)\n"
                    f"<code>{filename}</code>"
                )
            except Exception:
                pass

        await pyro.download_media(
            message=await pyro.get_messages(message.chat.id, message.message_id),
            file_name=str(input_path),
            progress=progress,
        )

        download_time = time.time() - download_start

        await status_msg.edit_text(
            f"📥 <b>Файл скачан за {format_duration(download_time)}</b>\n"
            f"📦 Размер: {format_size(doc.file_size)}\n\n"
            "⏳ Добавляю в очередь конвертации..."
        )

        position = queue.add_job(
            job_id=job_id,
            user_id=message.from_user.id,
            input_path=input_path,
            output_path=output_path,
            filename=filename,
        )

        if position > 1:
            await status_msg.edit_text(
                f"📋 <b>Файл в очереди</b>\n"
                f"📦 {format_size(doc.file_size)} | <code>{filename}</code>\n\n"
                f"🔢 Позиция в очереди: <b>{position}</b>"
            )

        result = await queue.wait_for_job(job_id)

        if result.status == JobStatus.DONE:
            convert_time = format_duration(result.duration)
            output_size = output_path.stat().st_size

            await status_msg.edit_text(
                f"⬆️ <b>Конвертация завершена!</b>\n"
                f"⏱ Время: {convert_time}\n"
                f"📦 Размер MP4: {format_size(output_size)}\n\n"
                "Отправляю файл..."
            )

            output_file = FSInputFile(output_path, filename=Path(filename).stem + ".mp4")
            await message.answer_document(
                output_file,
                caption=f"✅ <b>{Path(filename).stem}.mp4</b>\n"
                        f"⏱ Конвертировано за {convert_time}\n"
                        f"📦 {format_size(output_size)}"
            )
            await status_msg.delete()

        elif result.status == JobStatus.CANCELLED:
            await status_msg.edit_text("🛑 Задача была отменена.")

        else:
            await status_msg.edit_text(
                f"❌ <b>Ошибка конвертации</b>\n\n"
                f"<code>{result.error}</code>"
            )

    except Exception as e:
        logger.exception(f"Ошибка при обработке файла {filename}: {e}")
        await status_msg.edit_text(
            f"❌ <b>Неожиданная ошибка</b>\n\n<code>{str(e)}</code>"
        )
    finally:
        for path in [input_path, output_path]:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass


@dp.message()
async def handle_other(message: Message):
    if not is_allowed(message.from_user.id):
        return
    await message.answer(
        "📎 Пожалуйста, отправь <code>.mts</code> или <code>.m2ts</code> файл.\n"
        "Используй /start для информации."
    )


async def main():
    logger.info("Запуск MTS→MP4 бота...")
    await pyro.start()
    await queue.start()
    try:
        await dp.start_polling(bot, allowed_updates=["message"])
    finally:
        await queue.stop()
        await pyro.stop()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
