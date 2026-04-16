import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
Application,
CommandHandler,
ContextTypes,
MessageHandler,
filters,
)

BOT_TOKEN = “8632611940:AAEMcZqqs6-cXfunzW0aBlJ77BQ6-1QWHo0”

logging.basicConfig(
format=”%(asctime)s | %(levelname)s | %(message)s”,
level=logging.INFO,
)
log = logging.getLogger(**name**)

def convert_mts_to_mp4(src: Path, dst: Path):
cmd = [
“ffmpeg”, “-y”,
“-i”, str(src),
“-c:v”, “copy”,
“-c:a”, “aac”,
“-b:a”, “192k”,
str(dst),
]
result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode != 0:
return False, result.stderr[-500:]
return True, “”

def human_size(path: Path) -> str:
size = path.stat().st_size
for unit in (“B”, “KB”, “MB”, “GB”):
if size < 1024:
return f”{size:.1f} {unit}”
size /= 1024
return f”{size:.1f} TB”

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
await update.message.reply_text(
“MTS -> MP4 Converter\n\nОтправь файл .MTS - получишь .MP4.”,
)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
await update.message.reply_text(
“Отправь файл .MTS как документ - бот вернёт .MP4.\n\n”
“/start - приветствие\n/help - справка”
)

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
doc = update.message.document
filename = doc.file_name or “”

```
if not filename.lower().endswith(".mts"):
    await update.message.reply_text("Отправь файл с расширением .MTS")
    return

size_mb = doc.file_size / 1024 / 1024
status_msg = await update.message.reply_text(
    f"Получаю {filename} ({size_mb:.1f} MB)..."
)

with tempfile.TemporaryDirectory() as tmp_dir:
    tmp = Path(tmp_dir)
    src = tmp / filename
    dst = tmp / (Path(filename).stem + ".mp4")

    try:
        tg_file = await ctx.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(str(src))
    except Exception as e:
        await status_msg.edit_text(f"Ошибка скачивания: {e}")
        return

    await status_msg.edit_text(f"Конвертирую {filename}...")

    loop = asyncio.get_event_loop()
    ok, err = await loop.run_in_executor(None, convert_mts_to_mp4, src, dst)

    if not ok:
        await status_msg.edit_text(f"Ошибка конвертации:\n{err}")
        return

    out_name = dst.name
    await status_msg.edit_text(f"Отправляю {out_name} ({human_size(dst)})...")

    try:
        with open(dst, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=out_name,
                caption=f"Готово! {filename} -> {out_name}",
            )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"Ошибка отправки: {e}")
```

async def handle_other(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
await update.message.reply_text(“Отправь файл .MTS как документ. /help - справка”)

def main() -> None:
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler(“start”, cmd_start))
app.add_handler(CommandHandler(“help”, cmd_help))
app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
app.add_handler(MessageHandler(filters.ALL, handle_other))
log.info(“Бот запущен…”)
app.run_polling(drop_pending_updates=True)

if **name** == “**main**”:
main()
