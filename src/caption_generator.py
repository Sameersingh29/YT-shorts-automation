"""
Caption Generator — creates Hormozi-style ASS subtitle files.
Word-by-word pop animation with key word highlighting.
"""

from pathlib import Path

from src.config import (
    OUTPUT_WIDTH,
    OUTPUT_HEIGHT,
    CAPTION_FONT_NAME,
    CAPTION_FONT_SIZE,
    CAPTION_PRIMARY_COLOR,
    CAPTION_HIGHLIGHT_COLOR,
    CAPTION_OUTLINE_COLOR,
    CAPTION_BACK_COLOR,
    CAPTION_OUTLINE_WIDTH,
    CAPTION_SHADOW_DEPTH,
    CAPTION_Y_MARGIN,
    CAPTION_WORDS_PER_GROUP,
    CAPTION_POP_SCALE,
    CAPTION_POP_DURATION_MS,
    POWER_WORDS,
    get_logger,
)
from src.transcriber import WordTimestamp

logger = get_logger(__name__)


def _format_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format: H:MM:SS.cc (centiseconds)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def _is_power_word(word: str, extra_keywords: list[str] = None) -> bool:
    """Check if a word should be highlighted (power word or key word)."""
    cleaned = word.strip().lower().strip(".,!?;:'\"()-")
    all_keywords = POWER_WORDS.copy()
    if extra_keywords:
        all_keywords.update(w.lower() for w in extra_keywords)
    return cleaned in all_keywords


def _group_words(
    words: list[WordTimestamp],
    group_size: int = CAPTION_WORDS_PER_GROUP,
) -> list[list[WordTimestamp]]:
    """Group words into chunks for display (2-3 words per group)."""
    groups = []
    current_group = []

    for word in words:
        current_group.append(word)
        if len(current_group) >= group_size:
            groups.append(current_group)
            current_group = []

    # Don't leave a single word dangling — merge with previous group
    if current_group:
        if len(current_group) == 1 and groups:
            groups[-1].extend(current_group)
        else:
            groups.append(current_group)

    return groups


def generate_ass_captions(
    words: list[WordTimestamp],
    output_path: Path,
    clip_start_offset: float = 0.0,
    extra_keywords: list[str] = None,
) -> Path:
    """
    Generate an ASS subtitle file with Hormozi-style captions.

    Features:
        - Word groups (2-3 words at a time)
        - Pop-in scale animation per group
        - Key/power words highlighted in gold
        - Large bold font with black outline
        - Positioned below the centered video

    Args:
        words: List of WordTimestamp objects (timestamps relative to clip start).
        output_path: Where to save the .ass file.
        clip_start_offset: Offset to subtract from word timestamps
                          (if words have absolute timestamps from the full video).
        extra_keywords: Additional words to highlight beyond POWER_WORDS.

    Returns:
        Path to the generated .ass file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Adjust timestamps relative to clip start
    adjusted_words = []
    for w in words:
        adjusted_words.append(WordTimestamp(
            word=w.word,
            start=max(0, w.start - clip_start_offset),
            end=max(0, w.end - clip_start_offset),
        ))

    # Group words
    groups = _group_words(adjusted_words)

    # Build ASS file content
    ass_content = _build_ass_header()
    ass_content += "\n[Events]\n"
    ass_content += "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"

    for group in groups:
        if not group:
            continue

        start = group[0].start
        end = group[-1].end

        # Ensure minimum display duration (at least 300ms)
        if end - start < 0.3:
            end = start + 0.3

        # Build the display text with per-word styling
        text_parts = []
        for word in group:
            cleaned = word.word.strip()
            if not cleaned:
                continue

            display_word = cleaned.upper()  # Hormozi style: ALL CAPS

            if _is_power_word(cleaned, extra_keywords):
                # Highlighted power word (gold color + slightly larger)
                text_parts.append(
                    f"{{\\c{CAPTION_HIGHLIGHT_COLOR}\\fscx110\\fscy110}}"
                    f"{display_word}"
                    f"{{\\c{CAPTION_PRIMARY_COLOR}\\fscx100\\fscy100}}"
                )
            else:
                text_parts.append(display_word)

        display_text = " ".join(text_parts)

        # Add pop animation to the whole group
        pop = (
            f"{{\\fscx{CAPTION_POP_SCALE}\\fscy{CAPTION_POP_SCALE}"
            f"\\t(0,{CAPTION_POP_DURATION_MS},"
            f"\\fscx100\\fscy100)}}"
        )

        dialogue = (
            f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end)},"
            f"Default,,0,0,0,,{pop}{display_text}"
        )
        ass_content += dialogue + "\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    logger.info(
        f"Generated ASS captions: {len(groups)} word groups → {output_path.name}"
    )
    return output_path


def _build_ass_header() -> str:
    """Build the ASS file header with Hormozi caption styling."""
    return f"""[Script Info]
Title: YT Shorts Captions
ScriptType: v4.00+
PlayResX: {OUTPUT_WIDTH}
PlayResY: {OUTPUT_HEIGHT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{CAPTION_FONT_NAME},{CAPTION_FONT_SIZE},{CAPTION_PRIMARY_COLOR},&H000000FF,{CAPTION_OUTLINE_COLOR},{CAPTION_BACK_COLOR},-1,0,0,0,100,100,2,0,1,{CAPTION_OUTLINE_WIDTH},{CAPTION_SHADOW_DEPTH},5,10,10,{CAPTION_Y_MARGIN},1
"""
