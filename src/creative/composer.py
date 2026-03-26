from __future__ import annotations

"""Video composer - assembles final ad videos using FFmpeg.

Combines: product images + subtitle overlays + AI voiceover + BGM → final video
This is the "图文快切" (image slideshow) format proven to work on 千川.
"""

import subprocess
import uuid
from pathlib import Path


def get_image_duration(total_duration: float, image_count: int) -> float:
    """Calculate how long each image should be displayed."""
    return total_duration / max(image_count, 1)


def compose_video(
    images: list[str | Path],
    audio_path: str | Path,
    subtitles: list[dict],
    output_path: str | Path,
    bgm_path: str | Path | None = None,
    resolution: tuple[int, int] = (1080, 1920),  # 9:16 vertical
    bgm_volume: float = 0.15,
) -> Path:
    """Compose a 图文快切 style video from images, voiceover, and subtitles.

    Args:
        images: List of product image paths
        audio_path: Path to voiceover audio
        subtitles: List of {"text": str, "duration": float} for subtitle overlay
        output_path: Where to save the final video
        bgm_path: Optional background music
        resolution: Video resolution (width, height), default 1080x1920 (vertical)
        bgm_volume: BGM volume relative to voiceover (0.0-1.0)

    Returns:
        Path to the output video file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    width, height = resolution
    audio_path = Path(audio_path)

    # Get audio duration
    duration = _get_audio_duration(audio_path)
    if duration <= 0:
        duration = sum(s["duration"] for s in subtitles)

    image_dur = get_image_duration(duration, len(images))

    # Build FFmpeg filter complex
    filter_parts = []
    inputs = []

    # Input: images as a slideshow
    for i, img in enumerate(images):
        inputs.extend(["-loop", "1", "-t", str(image_dur), "-i", str(img)])
        # Scale and pad each image to target resolution
        filter_parts.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=white,"
            f"setsar=1[img{i}]"
        )

    # Concatenate all images
    concat_inputs = "".join(f"[img{i}]" for i in range(len(images)))
    filter_parts.append(f"{concat_inputs}concat=n={len(images)}:v=1:a=0[slideshow]")

    # Add Ken Burns effect (subtle zoom)
    filter_parts.append(
        f"[slideshow]zoompan=z='min(zoom+0.0008,1.15)':x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':d={int(duration * 25)}:s={width}x{height}:fps=25[zoomed]"
    )

    # Add subtitle overlays
    # Generate ASS subtitle file for precise timing
    ass_path = output_path.parent / f"subs_{uuid.uuid4().hex[:8]}.ass"
    _generate_ass_subtitles(subtitles, ass_path, width, height)
    filter_parts.append(f"[zoomed]ass='{ass_path}'[final_v]")

    # Audio input index
    audio_idx = len(images)
    inputs.extend(["-i", str(audio_path)])

    # Mix BGM if provided
    if bgm_path and Path(bgm_path).exists():
        bgm_idx = audio_idx + 1
        inputs.extend(["-i", str(bgm_path)])
        filter_parts.append(
            f"[{bgm_idx}:a]aloop=loop=-1:size=2e+09,atrim=0:{duration},"
            f"volume={bgm_volume}[bgm];"
            f"[{audio_idx}:a][bgm]amix=inputs=2:duration=first[final_a]"
        )
        audio_map = "[final_a]"
    else:
        audio_map = f"{audio_idx}:a"

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[final_v]",
        "-map", audio_map,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-t", str(duration),
        "-shortest",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-500:]}")

    # Clean up temp subtitle file
    ass_path.unlink(missing_ok=True)

    return output_path


def _get_audio_duration(audio_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _generate_ass_subtitles(
    segments: list[dict],
    output_path: Path,
    width: int,
    height: int,
) -> None:
    """Generate an ASS subtitle file with styled text overlays."""
    # Font size proportional to video height
    font_size = int(height * 0.038)
    margin_bottom = int(height * 0.12)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans SC,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,2.5,0,2,20,20,{margin_bottom},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    current_time = 0.0
    for seg in segments:
        start = _format_ass_time(current_time)
        end = _format_ass_time(current_time + seg["duration"])
        text = seg["text"].replace("\n", "\\N")
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
        current_time += seg["duration"]

    output_path.write_text(header + "\n".join(events), encoding="utf-8")


def _format_ass_time(seconds: float) -> str:
    """Format seconds to ASS time format (H:MM:SS.CC)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"
