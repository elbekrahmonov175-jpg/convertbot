FROM python:3.12-slim

# Устанавливаем ffmpeg и ffprobe
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Рабочая директория для временных файлов
ENV WORK_DIR=/tmp/convertbot
RUN mkdir -p /tmp/convertbot

CMD ["python", "bot.py"]
