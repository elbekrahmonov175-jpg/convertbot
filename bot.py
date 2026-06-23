import os
import asyncio
import subprocess
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8632611940:AAHVx5AP2lxNhIWN1JQmjeO49fqdLfJT-O8"
DOWNLOAD_DIR = Path("/tmp/mts_bot")
DOWNLOAD_DIR.mkdir(exist_ok=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я конвертирую MTS файлы в MP4 без потери качества и звука.\n\n"
        "📎 Просто отправь мне MTS файл как документ — и я верну тебе MP4!"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    filename = doc.file_name or "video"

    if not filename.lower().endswith(".mts"):
        await update.message.reply_text("❌ Это не MTS файл. Отправь файл с расширением .mts")
        return

    msg = await update.message.reply_text("⏳ Скачиваю файл...")

    input_path = DOWNLOAD_DIR / f"{doc.file_id}.mts"
    output_path = DOWNLOAD_DIR / f"{doc.file_id}.mp4"

    try:
        file = await context.bot.get_file(doc.file_id)
        await file.download_to_drive(str(input_path))

        await msg.edit_text("🔄 Конвертирую MTS → MP4 (без потери качества)...")

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
            await msg.edit_text("❌ Ошибка конвертации. Попробуй ещё раз.")
            return

        out_filename = Path(filename).stem + ".mp4"
        await msg.edit_text("📤 Отправляю MP4...")

        with open(output_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=out_filename,
                caption="✅ Готово! MP4 без потери качества и звука."
            )

        await msg.delete()

    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit_text(f"❌ Ошибка: {str(e)}")

    finally:
        if input_path.exists():
            input_path.unlink()
        if output_path.exists():
            output_path.unlink()


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    logger.info("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
