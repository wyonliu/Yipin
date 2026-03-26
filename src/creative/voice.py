from __future__ import annotations

"""Voice generation using MiniMax T2A (Text-to-Audio) API."""

import logging
import uuid
from pathlib import Path

import httpx

from config.settings import settings
from src.common.retry import with_retry

logger = logging.getLogger(__name__)


@with_retry(max_retries=3, base_delay=2.0, exceptions=(httpx.HTTPError, RuntimeError))
async def generate_voice(
    text: str,
    output_path: str | Path,
    voice_id: str | None = None,
    speed: float = 1.0,
    vol: float = 1.0,
    pitch: int = 0,
) -> Path:
    """Generate speech audio from text using MiniMax T2A v2.

    Args:
        text: Text to convert to speech (Chinese supported)
        output_path: Path to save the output audio file (mp3)
        voice_id: MiniMax voice ID, defaults to settings.minimax_tts_voice
        speed: Speech speed (0.5-2.0)
        vol: Volume (0.1-10.0)
        pitch: Pitch shift (-12 to 12)

    Returns:
        Path to the generated audio file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    voice = voice_id or settings.minimax_tts_voice

    payload = {
        "model": "speech-01-turbo",
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice,
            "speed": speed,
            "vol": vol,
            "pitch": pitch,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
        },
    }

    headers = {
        "Authorization": f"Bearer {settings.minimax_api_key}",
        "Content-Type": "application/json",
    }

    url = settings.minimax_tts_url
    if settings.minimax_group_id:
        url = f"{url}?GroupId={settings.minimax_group_id}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()

    # MiniMax T2A v2 returns base_resp with status_code
    base_resp = result.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise RuntimeError(
            f"MiniMax TTS failed: code={base_resp.get('status_code')}, "
            f"message={base_resp.get('status_msg')}"
        )

    # Audio data is in data.audio — hex-encoded audio bytes
    audio_hex = result.get("data", {}).get("audio", "")
    if not audio_hex:
        # Some versions return audio directly
        audio_hex = result.get("audio", "")

    if not audio_hex:
        raise RuntimeError("MiniMax TTS returned empty audio data")

    audio_bytes = bytes.fromhex(audio_hex)
    output_path.write_bytes(audio_bytes)
    logger.info(f"Voice generated: {output_path} ({len(audio_bytes)} bytes)")
    return output_path


async def generate_voice_for_script(script: dict, output_dir: str | Path) -> dict:
    """Generate voice audio for a complete script, returning paths and timing info.

    Args:
        script: Script dict with 'full_script' and 'subtitle_segments'
        output_dir: Directory to save audio files

    Returns:
        Dict with 'audio_path' and 'duration_estimate'
    """
    output_dir = Path(output_dir)

    full_text = script["full_script"]
    audio_path = output_dir / f"voice_{uuid.uuid4().hex[:8]}.mp3"

    await generate_voice(full_text, audio_path)

    return {
        "audio_path": str(audio_path),
        "duration_estimate": script.get("estimated_duration", 20),
    }
