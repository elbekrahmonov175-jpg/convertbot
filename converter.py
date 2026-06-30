import asyncio
import logging
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
    """
    import time
    start = time.time()

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-nostats",
        "-loglevel", "error",
        str(output_path),
    ]

    logger.info(f"Запуск ffmpeg: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_text = stderr.decode("utf-8", errors="replace")
        logger.error(f"ffmpeg завершился с ошибкой:\n{error_text}")
        raise RuntimeError(_extract_ffmpeg_error(error_text))

    elapsed = time.time() - start
    logger.info(f"Конвертация завершена за {elapsed:.1f}с: {output_path}")
    return elapsed


def _extract_ffmpeg_error(stderr_text: str) -> str:
    lines = [l.strip() for l in stderr_text.splitlines() if l.strip()]
    error_lines = [l for l in lines if any(
        kw in l.lower() for kw in ["error", "invalid", "no such", "permission", "failed"]
    )]
    if error_lines:
        return error_lines[-1][:300]
    return "\n".join(lines[-3:])[:300] if lines else "Неизвестная ошибка ffmpeg"
