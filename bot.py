import asyncio
import logging
import os
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = 33897982
API_HASH = "158332efe54c552a47fa6916fbcb30a5"
BOT_TOKEN = "8632611940:AAHVx5AP2lxNhIWN1JQmjeO49fqdLfJT-O8"

DOWNLOAD_DIR = Path("/tmp/mts_bot")
DOWNLOAD_DIR.mkdir(exist_ok=True)

bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)


@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    await event.reply(
        "👋 Привет! Я конвертирую MTS файлы в MP4 без потери качества и звука.\n\n"
        "📎 Просто отправь мне MTS файл как документ — и я верну тебе MP4!\n\n"
        "⚡ Лимит файла: до 2 ГБ"
    )


@bot.on(events.NewMessage(func=lambda e: e.document))
async def handle_document(event):
    doc = event.document
    filename = ""

    for attr in doc.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            filename = attr.file_name
            break

    if not filename.lower().endswith(".mts"):
        await event.reply("❌ Это не MTS файл. Отправь файл с расширением .mts")
        return

    msg = await event.reply("⏳ Скачиваю файл...")

    file_id = str(doc.id)
    input_path = DOWNLOAD_DIR / f"{file_id}.mts"
    output_path = DOWNLOAD_DIR / f"{file_id}.mp4"

    try:
        await bot.download_media(event.message, file=str(input_path))

        await msg.edit("🔄 Конвертирую MTS → MP4 (без потери качества)...")

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-c:v", "copy",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path)
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"ffmpeg error: {stderr.decode()}")
            await msg.edit("❌ Ошибка конвертации. Попробуй ещё раз.")
            return

        out_filename = Path(filename).stem + ".mp4"
        file_size_mb = output_path.stat().st_size / (1024 * 1024)

        await msg.edit(f"📤 Отправляю MP4 ({file_size_mb:.1f} МБ)...")

        await bot.send_file(
            event.chat_id,
            str(output_path),
            attributes=[DocumentAttributeFilename(out_filename)],
            caption="✅ Готово! MP4 без потери качества и звука.",
            reply_to=event.message.id
        )

        await msg.delete()

    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit(f"❌ Ошибка: {str(e)}")

    finally:
        if input_path.exists():
            input_path.unlink()
        if output_path.exists():
            output_path.unlink()


async def main():
    logger.info("Bot started (Telethon, limit 2GB)...")
    await bot.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
