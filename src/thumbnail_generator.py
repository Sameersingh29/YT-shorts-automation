"""
Thumbnail Generator — creates eye-catching thumbnails for YouTube Shorts.
Uses Pillow to composite: video frame + gradient overlay + bold text.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from src.config import (
    THUMBNAIL_WIDTH,
    THUMBNAIL_HEIGHT,
    FONTS_DIR,
    CAPTION_FONT_FILE,
    TEMP_DIR,
    get_logger,
)
from src.video_processor import extract_frame

logger = get_logger(__name__)

# Gradient colors (dark cinematic feel)
GRADIENT_TOP = (0, 0, 0, 0)         # Transparent at top
GRADIENT_BOTTOM = (0, 0, 0, 200)    # Dark at bottom

# Text settings
TITLE_COLOR = (255, 255, 255)        # White
ACCENT_COLOR = (255, 215, 0)         # Gold
OUTLINE_COLOR = (0, 0, 0)            # Black


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Load Montserrat ExtraBold font, fall back to default if not found."""
    font_path = FONTS_DIR / CAPTION_FONT_FILE
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size)

    # Try system fonts as fallback
    fallbacks = ["Impact", "Arial Black", "arialbd.ttf", "impact.ttf"]
    for name in fallbacks:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue

    logger.warning("No bold font found, using default. Download Montserrat ExtraBold!")
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text to fit within a maximum pixel width."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = font.getbbox(test_line)
        text_width = bbox[2] - bbox[0]

        if text_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))

    return lines


def _draw_text_with_outline(
    draw: ImageDraw.Draw,
    position: tuple,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    outline_color: tuple = OUTLINE_COLOR,
    outline_width: int = 3,
) -> None:
    """Draw text with a thick outline for readability."""
    x, y = position
    # Draw outline
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    # Draw main text
    draw.text(position, text, font=font, fill=fill)


def generate_thumbnail(
    video_path: Path,
    timestamp: float,
    title: str,
    output_path: Path,
    hook: str = "",
) -> Path | None:
    """
    Generate a YouTube Shorts thumbnail.

    Design:
        - Background: blurred + darkened video frame
        - Center: clear video frame (slightly smaller)
        - Bottom: gradient overlay with bold title text
        - Top: optional hook/tagline in accent color

    Args:
        video_path: Path to the clip video.
        timestamp: Time in seconds to extract the background frame.
        title: Main title text for the thumbnail.
        output_path: Where to save the thumbnail.
        hook: Optional hook text for the top of thumbnail.

    Returns:
        Path to the generated thumbnail, or None on complete failure.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Helper: save a PIL image as JPEG, falling back to PNG if JPEG fails
    def _save_jpeg(img: "Image.Image", path: Path) -> Path:
        """Save image as JPEG; if JPEG encoder is unavailable, save as PNG."""
        try:
            img.convert("RGB").save(str(path), "JPEG", quality=90)
            return path
        except Exception as e:
            logger.warning(f"JPEG save failed ({e}), falling back to PNG")
            png_path = path.with_suffix(".png")
            img.convert("RGB").save(str(png_path), "PNG")
            return png_path

    # Extract a frame from the video
    frame_path = TEMP_DIR / "thumb_frame.jpg"
    try:
        extract_frame(video_path, timestamp, frame_path)
    except Exception as e:
        logger.warning(f"Frame extraction failed ({e}), using black placeholder")

    try:
        # Load frame — validate size first (ffmpeg can exit 0 with tiny/corrupt files)
        if not frame_path.exists() or frame_path.stat().st_size < 1024:
            logger.warning(
                f"Frame file missing or too small "
                f"({frame_path.stat().st_size if frame_path.exists() else 0} bytes). "
                "Falling back to black placeholder."
            )
            frame = Image.new("RGBA", (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), (10, 10, 10, 255))
        else:
            try:
                frame = Image.open(frame_path).convert("RGBA")
                frame = frame.resize((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS)
            except Exception as e:
                logger.warning(f"Pillow could not open frame ({e}), using black placeholder")
                frame = Image.new("RGBA", (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), (10, 10, 10, 255))

        # Enhance — force back to RGBA after each step because some Pillow
        # versions lose the alpha channel during enhancement.
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Contrast(frame)
        frame = enhancer.enhance(1.3).convert("RGBA")
        enhancer = ImageEnhance.Color(frame)
        frame = enhancer.enhance(1.2).convert("RGBA")

        # Create gradient overlay
        gradient = Image.new("RGBA", (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), (0, 0, 0, 0))
        draw_gradient = ImageDraw.Draw(gradient)

        # Bottom gradient (dark for text readability)
        for y in range(THUMBNAIL_HEIGHT // 2, THUMBNAIL_HEIGHT):
            progress = (y - THUMBNAIL_HEIGHT // 2) / (THUMBNAIL_HEIGHT // 2)
            alpha = int(200 * progress)
            draw_gradient.line([(0, y), (THUMBNAIL_WIDTH, y)], fill=(0, 0, 0, alpha))

        # Top gradient (subtle dark for hook text)
        for y in range(THUMBNAIL_HEIGHT // 4):
            progress = 1 - (y / (THUMBNAIL_HEIGHT // 4))
            alpha = int(120 * progress)
            draw_gradient.line([(0, y), (THUMBNAIL_WIDTH, y)], fill=(0, 0, 0, alpha))

        # Composite frame + gradient (both must be RGBA)
        thumb = Image.alpha_composite(frame, gradient)

        # Draw text
        draw = ImageDraw.Draw(thumb)

        title_font = _get_font(56)
        title_lines = _wrap_text(title.upper(), title_font, THUMBNAIL_WIDTH - 80)

        line_height = 70
        total_text_height = len(title_lines) * line_height
        y_start = THUMBNAIL_HEIGHT - total_text_height - 40

        for i, line in enumerate(title_lines):
            bbox = title_font.getbbox(line)
            text_width = bbox[2] - bbox[0]
            x = (THUMBNAIL_WIDTH - text_width) // 2
            y = y_start + i * line_height
            _draw_text_with_outline(draw, (x, y), line, title_font, TITLE_COLOR)

        if hook:
            hook_font = _get_font(32)
            _draw_text_with_outline(
                draw, (30, 25), hook.upper(), hook_font, ACCENT_COLOR, outline_width=2
            )

        saved_path = _save_jpeg(thumb, output_path)

    except Exception as e:
        # Last-resort fallback: plain dark image with just the title text
        logger.warning(f"Thumbnail compositing failed ({e}), generating plain text thumbnail")
        try:
            fallback = Image.new("RGB", (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), (15, 15, 20))
            draw = ImageDraw.Draw(fallback)
            font = _get_font(48)
            lines = _wrap_text(title.upper(), font, THUMBNAIL_WIDTH - 80)
            for i, line in enumerate(lines):
                bbox = font.getbbox(line)
                x = (THUMBNAIL_WIDTH - (bbox[2] - bbox[0])) // 2
                y = THUMBNAIL_HEIGHT // 2 - len(lines) * 30 + i * 60
                draw.text((x, y), line, font=font, fill=(255, 255, 255))
            saved_path = _save_jpeg(fallback, output_path)
        except Exception as e2:
            logger.error(f"Thumbnail generation completely failed ({e2}), skipping thumbnail")
            # Cleanup temp frame
            try:
                frame_path.unlink()
            except OSError:
                pass
            return None

    # Cleanup temp frame
    try:
        frame_path.unlink()
    except OSError:
        pass

    file_size_kb = saved_path.stat().st_size / 1024
    logger.info(f"Thumbnail generated → {saved_path.name} ({file_size_kb:.0f} KB)")
    return saved_path

