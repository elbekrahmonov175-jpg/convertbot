import asyncio
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


async def convert_mts_to_mp4(
    input_path: Path,
    output_path: Path,
    progress_callback=None,
) -> float:
    """
    Конвертирует MTS/M2TS файл в MP4.
    Использует -c copy для максимальной скорости (без перекодирования).
    Возвращает длительность конвертации в секундах.
    Вызывает progress_callback(percent: float) если передан.
    """
    import time
    start = time.time()

    # Сначала получим длительность файла для прогресса
    duration_seconds = await _get_duration(input_path)

    cmd = [
        "ffmpeg",
        "-y",                        # перезаписать если есть
        "-i", str(input_path),       # входной файл
        "-c:v", "copy",              # копировать видео без перекодирования
        "-c:a", "aac",               # аудио в AAC (совместимо с MP4)
        "-b:a", "192k",              # битрейт аудио
        "-movflags", "+faststart",   # оптимизация для стриминга
        "-progress", "pipe:1",       # прогресс в stdout
        "-nostats",
        str(output_path),
    ]

    logger.info(f"Запуск ffmpeg: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Читаем прогресс из stdout
    if progress_callback and duration_seconds:
        asyncio.create_task(
            _read_progress(proc.stdout, duration_seconds, progress_callback)
        )
    elif proc.stdout:
        asyncio.create_task(_drain(proc.stdout))

    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_text = stderr.decode("utf-8", errors="replace")
        logger.error(f"ffmpeg завершился с ошибкой:\n{error_text}")
        raise RuntimeError(_extract_ffmpeg_error(error_text))

    elapsed = time.time() - start
    logger.info(f"Конвертация завершена за {elapsed:.1f}с: {output_path}")
    return elapsed


async def _get_duration(input_path: Path) -> float | None:
    """Получает длительность файла через ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip())
    except Exception:
        return None


async def _read_progress(stdout, duration: float, callback):
    """Читает прогресс из ffmpeg -progress pipe:1"""
    current_time = 0.0
    async for line in stdout:
        line = line.decode("utf-8", errors="replace").strip()
        if line.startswith("out_time_ms="):
            try:
                ms = int(line.split("=")[1])
                current_time = ms / 1_000_000
                percent = min(current_time / duration * 100, 99.0)
                await callback(percent)
            except (ValueError, ZeroDivisionError):
                pass


async def _drain(stdout):
    """Просто читаем stdout чтобы не было deadlock."""
    async for _ in stdout:
        pass


def _extract_ffmpeg_error(stderr_text: str) -> str:
    """Извлекает последнюю значимую строку ошибки из вывода ffmpeg."""
    lines = [l.strip() for l in stderr_text.splitlines() if l.strip()]
    # Ищем строки с ошибками
    error_lines = [l for l in lines if any(
        kw in l.lower() for kw in ["error", "invalid", "no such", "permission", "failed"]
    )]
    if error_lines:
        return error_lines[-1][:300]
    # Иначе последние строки
    return "\n".join(lines[-3:])[:300] if lines else "Неизвестная ошибка ffmpeg"
