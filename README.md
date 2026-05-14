# 🎬 YT Shorts Automation

Fully automated pipeline that converts long-form podcast videos into viral YouTube Shorts — completely free.

## What It Does

1. **Downloads** podcast videos from Google Drive
2. **Transcribes** with word-level timestamps (faster-whisper)
3. **AI-selects** the 10 best moments using Gemini (mix of viral + informative)
4. **Processes** each clip: 9:16 split layout + Hormozi-style captions
5. **Generates** thumbnails, titles, descriptions, and hashtags
6. **Uploads** 2 clips/day to YouTube at 9 AM & 9 PM IST
7. **Tracks** performance on a live analytics dashboard

## Cost: $0/month

| Component | Service | Cost |
|---|---|---|
| AI | Gemini 2.0 Flash (free tier) | Free |
| Video Processing | FFmpeg | Free |
| Transcription | faster-whisper | Free |
| Hosting | GitHub Actions (2000 min/month) | Free |
| Storage | Google Drive (15 GB) | Free |
| Uploads | YouTube Data API v3 | Free |
| Dashboard | GitHub Pages | Free |

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/yt-shorts-automation.git
cd yt-shorts-automation
pip install -r requirements.txt
```

### 2. Set Up Credentials

```bash
python scripts/setup_google_auth.py
```

This interactive wizard will help you set up:
- Google Cloud service account (for Drive access)
- YouTube OAuth2 (for video uploads)
- Drive folder IDs (source & queue)

### 3. Get a Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Create a free API key
3. Add to `.env`: `GEMINI_API_KEY=your_key_here`

### 4. Verify Setup

```bash
python scripts/check_apis.py
```

### 5. Process Your First Video

```bash
# Put a podcast video in your Google Drive source folder, then:
python process_video.py
```

### 6. Upload a Clip

```bash
python upload_clip.py --slot morning
```

### 7. Deploy to GitHub Actions

1. Push to GitHub
2. Go to Settings → Secrets → Actions
3. Add these secrets:
   - `GOOGLE_SERVICE_ACCOUNT_JSON`
   - `GEMINI_API_KEY`
   - `YOUTUBE_CLIENT_SECRET_JSON`
   - `YOUTUBE_REFRESH_TOKEN`
   - `DRIVE_SOURCE_FOLDER_ID`
   - `DRIVE_QUEUE_FOLDER_ID`

The workflows will run automatically:
- **Process Video**: Every 3 days (or manually)
- **Upload Clip**: Daily at 9 AM & 9 PM IST

## Project Structure

```
├── .github/workflows/
│   ├── process_video.yml    # Video processing workflow
│   └── upload_clip.yml      # Daily upload workflow
├── src/
│   ├── config.py            # Configuration
│   ├── drive_handler.py     # Google Drive operations
│   ├── transcriber.py       # Whisper transcription
│   ├── clip_selector.py     # Gemini clip selection
│   ├── video_processor.py   # FFmpeg processing
│   ├── caption_generator.py # Hormozi-style captions
│   ├── thumbnail_generator.py
│   ├── metadata_generator.py
│   ├── youtube_uploader.py  # YouTube API
│   ├── queue_manager.py     # Clip queue
│   └── analytics.py         # Performance tracking
├── dashboard/               # GitHub Pages analytics
├── data/                    # Queue & analytics JSON
├── scripts/                 # Setup helpers
├── process_video.py         # Main processing script
└── upload_clip.py           # Main upload script
```

## Video Output Format

- **Resolution**: 1080×1920 (9:16 vertical)
- **Layout**: Original video centered, blurred background fill
- **Captions**: Hormozi-style word-by-word pop animation
- **Font**: Montserrat Extra Bold
- **Duration**: 30-45 seconds per clip

## License

MIT
