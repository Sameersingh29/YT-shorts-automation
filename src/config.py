"""
Configuration constants for YT Shorts Automation.
Loads settings from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Paths ────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
TEMP_DIR = BASE_DIR / "temp"
FONTS_DIR = BASE_DIR / "templates" / "fonts"

# Ensure directories exist
TEMP_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# ─── Google Cloud ─────────────────────────────────────────
GOOGLE_PROJECT_ID = os.environ.get("GOOGLE_PROJECT_ID", "yt-automation-496118")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# ─── Google Drive ─────────────────────────────────────────
DRIVE_SOURCE_FOLDER_ID = os.environ.get("DRIVE_SOURCE_FOLDER_ID", "")
DRIVE_QUEUE_FOLDER_ID = os.environ.get("DRIVE_QUEUE_FOLDER_ID", "")

# ─── Gemini AI ────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"

# ─── YouTube ──────────────────────────────────────────────
YOUTUBE_CLIENT_SECRET_JSON = os.environ.get("YOUTUBE_CLIENT_SECRET_JSON", "")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")

# ─── Video Output Dimensions (9:16) ──────────────────────
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920

# Original 16:9 video scaled to fit width
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 608  # 1080 * 9/16 ≈ 608

# Centered vertically: (1920 - 608) / 2 = 656
VIDEO_Y_OFFSET = (OUTPUT_HEIGHT - VIDEO_HEIGHT) // 2  # 656

# ─── Caption Style (Hormozi) ─────────────────────────────
CAPTION_FONT_NAME = "Montserrat ExtraBold"
CAPTION_FONT_FILE = "Montserrat-ExtraBold.ttf"
CAPTION_FONT_SIZE = 60
CAPTION_PRIMARY_COLOR = "&H00FFFFFF"     # White (ASS: AABBGGRR)
CAPTION_HIGHLIGHT_COLOR = "&H0000D7FF"   # Gold/Yellow
CAPTION_OUTLINE_COLOR = "&H00000000"     # Black outline
CAPTION_BACK_COLOR = "&H80000000"        # Semi-transparent black shadow
CAPTION_OUTLINE_WIDTH = 4
CAPTION_SHADOW_DEPTH = 2
CAPTION_Y_MARGIN = 420  # MarginV in ASS style — positions captions below video
CAPTION_WORDS_PER_GROUP = 3
CAPTION_POP_SCALE = 130  # Start scale % for pop animation
CAPTION_POP_DURATION_MS = 150  # Animation duration in ms

# Power words to auto-highlight in captions
POWER_WORDS = {
    "money", "rich", "wealth", "million", "billion", "cash", "invest",
    "discipline", "stoic", "mindset", "grind", "hustle", "focus",
    "power", "success", "freedom", "legacy", "empire", "win", "dominate",
    "never", "always", "everything", "nothing", "impossible", "insane",
    "lambo", "ferrari", "porsche", "supercar", "luxury",
    "truth", "secret", "hack", "mistake", "wrong", "right",
    "love", "hate", "fear", "pain", "sacrifice", "fire",
}

# ─── Clip Settings ────────────────────────────────────────
MIN_CLIP_DURATION = 30   # seconds
MAX_CLIP_DURATION = 45   # seconds
CLIPS_PER_VIDEO = 10
UPLOADS_PER_DAY = 2

# ─── Schedule (IST = UTC+5:30) ───────────────────────────
SCHEDULE_TIMES_IST = ["09:00", "21:00"]
IST_UTC_OFFSET_HOURS = 5.5

# ─── Whisper (Transcription) ─────────────────────────────
WHISPER_MODEL = "base"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

# ─── Thumbnail ────────────────────────────────────────────
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720

# ─── Podcast Topics (for AI prompt tuning) ───────────────
PODCAST_TOPICS = [
    "money", "finance", "investing",
    "motivation", "self-improvement",
    "stoicism", "philosophy",
    "cars", "supercars", "luxury",
    "entrepreneurship", "business",
    "discipline", "mindset",
]

# ─── Logging ──────────────────────────────────────────────
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def get_logger(name: str) -> logging.Logger:
    """Get a named logger instance."""
    return logging.getLogger(name)
