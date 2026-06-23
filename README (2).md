# MTS → MP4 Telegram Bot

Конвертирует MTS файлы в MP4 без потери качества и звука через ffmpeg.

## Деплой на Railway

1. Залей эти файлы на GitHub (новый репозиторий)
2. Зайди на [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Выбери свой репо — Railway сам подхватит `nixpacks.toml` и установит ffmpeg
4. Готово!

## Файлы

- `bot.py` — весь бот в одном файле
- `requirements.txt` — зависимости Python
- `nixpacks.toml` — конфиг Railway (устанавливает Python + ffmpeg)
