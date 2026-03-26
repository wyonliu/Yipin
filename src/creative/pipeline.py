from __future__ import annotations

"""Creative production pipeline - orchestrates the full content generation flow.

Flow: Product config → Script generation → TTS voiceover → Video composition → Ready for upload
"""

import uuid
from pathlib import Path

import yaml

from src.creative.scriptwriter import generate_scripts
from src.creative.voice import generate_voice_for_script
from src.creative.composer import compose_video


WORKSPACE = Path("workspace")
PRODUCTS_CONFIG = Path("config/products.yaml")


def load_products() -> dict:
    """Load product configurations from YAML."""
    with open(PRODUCTS_CONFIG) as f:
        data = yaml.safe_load(f)
    return data.get("products", {})


async def produce_creatives_for_product(
    product_key: str,
    count: int = 5,
    top_performers: list[dict] | None = None,
    merchant_id: str | None = None,
) -> list[dict]:
    """Full pipeline: generate scripts → voice → video for one product.

    Args:
        product_key: Key in products.yaml (or merchant DB)
        count: Number of creatives to produce
        top_performers: Historical top performers for feedback loop
        merchant_id: If provided, load product from DB instead of YAML

    Returns:
        List of creative records with paths and metadata
    """
    if merchant_id:
        from src.common.tenant import get_merchant_products
        products = get_merchant_products(merchant_id)
    else:
        products = load_products()
    product = products[product_key]

    batch_id = uuid.uuid4().hex[:8]
    batch_dir = WORKSPACE / "creatives" / f"{product_key}_{batch_id}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Generate scripts
    scripts = await generate_scripts(product, count=count, top_performers=top_performers)

    creatives = []
    for i, script in enumerate(scripts):
        creative_id = f"{batch_id}_{i:02d}"
        creative_dir = batch_dir / creative_id
        creative_dir.mkdir(exist_ok=True)

        # Step 2: Generate voiceover
        voice_result = await generate_voice_for_script(script, creative_dir)

        # Step 3: Compose video
        images = _get_product_images(product)
        if not images:
            # Fallback: generate placeholder
            images = [_create_text_card(script["hook"], creative_dir / "hook_card.png")]

        # Select BGM
        bgm = _select_bgm(script.get("angle", ""))

        output_video = creative_dir / f"creative_{creative_id}.mp4"
        compose_video(
            images=images,
            audio_path=voice_result["audio_path"],
            subtitles=script["subtitle_segments"],
            output_path=output_video,
            bgm_path=bgm,
        )

        creative_record = {
            "id": creative_id,
            "batch_id": batch_id,
            "merchant_id": merchant_id,
            "product_key": product_key,
            "product_name": product["name"],
            "script": script,
            "video_path": str(output_video),
            "audio_path": voice_result["audio_path"],
            "duration": voice_result["duration_estimate"],
            "angle": script.get("angle", "unknown"),
            "hook": script.get("hook", ""),
            "status": "ready",  # ready → uploaded → active → paused → stopped
        }
        creatives.append(creative_record)

    return creatives


async def produce_daily_batch(
    top_performers: list[dict] | None = None,
    merchant_id: str | None = None,
) -> list[dict]:
    """Produce the daily batch of creatives for all active products.

    Returns:
        All creative records generated today
    """
    from config.settings import settings

    if merchant_id:
        from src.common.tenant import get_merchant_products
        products = get_merchant_products(merchant_id)
    else:
        products = load_products()

    all_creatives = []
    per_product = settings.videos_per_product
    for key in products:
        product_creatives = await produce_creatives_for_product(
            key, count=per_product, top_performers=top_performers,
            merchant_id=merchant_id,
        )
        all_creatives.extend(product_creatives)

    return all_creatives


def _get_product_images(product: dict) -> list[Path]:
    """Get product images from the configured directory."""
    images_dir = Path(product.get("images_dir", ""))
    if not images_dir.exists():
        return []

    extensions = {".jpg", ".jpeg", ".png", ".webp"}
    images = sorted(
        p for p in images_dir.iterdir()
        if p.suffix.lower() in extensions
    )
    return images[:8]  # Max 8 images per video


def _create_text_card(text: str, output_path: Path) -> Path:
    """Create a simple text-on-background image as fallback."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1080, 1920), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("assets/fonts/NotoSansSC-Bold.ttf", 72)
    except OSError:
        font = ImageFont.load_default()

    # Word wrap
    lines = []
    current = ""
    for char in text:
        current += char
        if len(current) >= 12:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)

    y = 700
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((1080 - w) / 2, y), line, fill=(30, 30, 30), font=font)
        y += 100

    img.save(output_path)
    return output_path


def _select_bgm(angle: str) -> Path | None:
    """Select appropriate BGM based on creative angle."""
    bgm_dir = Path("assets/bgm")
    if not bgm_dir.exists():
        return None

    bgm_files = list(bgm_dir.glob("*.mp3"))
    if not bgm_files:
        return None

    # Simple selection: hash angle to pick a consistent BGM
    idx = hash(angle) % len(bgm_files)
    return bgm_files[idx]
