#!/usr/bin/env python3
import asyncio, logging, os, subprocess, tempfile
from pathlib import Path
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.environ.get(‘BOT_TOKEN’, ‘8632611940:AAEMcZqqs6-cXfunzW0aBlJ77BQ6-1QWHo0’)

logging.basicConfig(format=’%(asctime)s %(levelname)s %(message)s’, level=logging.INFO)
log = logging.getLogger(**name**)

def convert(src: Path, dst: Path):
r = subprocess.run([‘ffmpeg’, ‘-y’, ‘-i’, str(src), ‘-c:v’, ‘copy’, ‘-c:a’, ‘aac’, str(dst)], capture_output=True, text=True)
return r.returncode == 0, r.stderr[-400:]

def sz(p: Path):
s = p.stat().st_size
for u in (‘B’, ‘KB’, ‘MB’, ‘GB’):
if s < 1024: return f’{s:.1f}’ + ’ ’ + u
s /= 1024
return str(s)

async def start(u, c): await u.message.reply_text(‘MTS->MP4 бот. Отправь .MTS файл как документ.’)

async def doc(u: Update, c: ContextTypes.DEFAULT_TYPE):
d = u.message.document
fn = d.file_name or ‘’
if not fn.lower().endswith(’.mts’):
await u.message.reply_text(‘Нужен файл .MTS’); return
msg = await u.message.reply_text(f’Скачиваю {fn}…’)
with tempfile.TemporaryDirectory() as td:
tmp = Path(td)
src = tmp / fn
dst = tmp / (Path(fn).stem + ‘.mp4’)
try:
tf = await c.bot.get_file(d.file_id)
await tf.download_to_drive(str(src))
except Exception as e:
await msg.edit_text(f’Ошибка скачивания: {e}’); return
await msg.edit_text(‘Конвертирую…’)
ok, err = await asyncio.get_event_loop().run_in_executor(None, convert, src, dst)
if not ok:
await msg.edit_text(f’Ошибка ffmpeg: {err}’); return
await msg.edit_text(f’Отправляю {dst.name}…’)
with open(dst, ‘rb’) as f:
await u.message.reply_document(f, filename=dst.name, caption=‘Готово!’)
await msg.delete()

async def other(u, c): await u.message.reply_text(‘Отправь .MTS файл как документ’)

def main():
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler(‘start’, start))
app.add_handler(MessageHandler(filters.Document.ALL, doc))
app.add_handler(MessageHandler(filters.ALL, other))
log.info(‘Bot started’)
app.run_polling(drop_pending_updates=True)

if **name** == ‘**main**’: main()
