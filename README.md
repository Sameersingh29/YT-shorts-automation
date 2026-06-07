# 🎬 YT Shorts Automation

Fully automated pipeline that converts long-form podcast videos into viral YouTube Shorts — completely free.

## What It Does

1. **Downloads** podcast videos from Google Drive
2. **Transcribes** with word-level timestamps (faster-whisper)
3. **AI-selects** the best moments using Gemini (mix of viral + informative)
4. **Processes** each clip: 9:16 split layout + Hormozi-style captions
5. **Generates** thumbnails, titles, descriptions, and hashtags
6. **Uploads** 2 clips/day to YouTube at 9 AM & 9 PM IST
7. **Tracks** performance on a live analytics dashboard

## Cost: $0/month

| Component | Service | Cost |
|---|---|---|
| AI | Gemini 2.5 Flash (free tier) | Free |
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

This interactive wizard will guide you through:
- **Service account** (for reading source videos from Google Drive)
- **YouTube OAuth2** (for YouTube uploads *and* Drive queue uploads — see note below)
- **Drive folder IDs** (source & queue)

> **Important — Two-Account Setup:**
> The pipeline uses two different auth methods for Drive:
> - **Downloads** (source videos): service account credentials — the source folder must be shared with the service account email.
> - **Uploads** (processed clips → queue): your YouTube OAuth credentials — the **queue folder must be shared (as Editor) with the Google account you use for YouTube OAuth**.
>
> If your YouTube account and your Google Drive account are different, open the queue folder in Drive and share it with your YouTube account's email address before running the pipeline.

### 3. Get a Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Create a free API key
3. Add to `.env`: `GEMINI_API_KEY=your_key_here`

### 4. Verify Setup

```bash
# Check all APIs and credentials
python scripts/check_apis.py

# Check Drive folder access for the OAuth account specifically
python scripts/check_drive_access.py
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
│   ├── config.py            # Configuration & constants
│   ├── drive_handler.py     # Google Drive (SA for reads, OAuth for writes)
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
├── scripts/
│   ├── setup_google_auth.py # Interactive auth wizard
│   ├── check_apis.py        # Full API health check
│   └── check_drive_access.py # Drive folder access diagnostic
├── process_video.py         # Main processing script
└── upload_clip.py           # Main upload script
```

## Video Output Format

- **Resolution**: 1080×1920 (9:16 vertical)
- **Layout**: Original video centered, blurred background fill
- **Captions**: Hormozi-style word-by-word pop animation
- **Font**: Montserrat Extra Bold
- **Duration**: 30-45 seconds per clip

## Troubleshooting

### "All videos in source folder have been processed"
A previous run failed mid-pipeline and marked the video as done with 0 clips. The pipeline now automatically skips marking a video as processed if no clips were successfully queued — so failed runs are retried on the next execution. If you hit this with an older run, clear `data/processed_videos.json`.

### "storageQuotaExceeded" on Drive upload
Service accounts have no Drive storage quota and cannot upload to regular My Drive folders. The pipeline routes uploads through your YouTube OAuth credentials instead. Make sure the queue folder is shared (Editor) with the Google account used for YouTube OAuth.

### "File not found" on queue folder (404)
The OAuth account doesn't have access to the queue folder. Run `python scripts/check_drive_access.py` to identify which account the OAuth token belongs to, then share the queue folder with that account in Google Drive.

### "invalid_scope" on Drive upload
Your stored `YOUTUBE_REFRESH_TOKEN` was obtained without the Drive scope. Re-run `python scripts/setup_google_auth.py` (option 2) to get a new token that includes both YouTube and Drive scopes.

### "invalid_grant: Token has been expired or revoked"
Your `YOUTUBE_REFRESH_TOKEN` has expired. By default, Google puts new OAuth apps in "Testing" mode, which forces tokens to expire exactly 7 days after generation. To fix this permanently:
1. Go to the [Google Cloud Console](https://console.cloud.google.com/) -> APIs & Services -> OAuth consent screen.
2. Click **Publish App** to change the status to "In production" (you don't actually need to pass verification for a personal app).
3. Re-run `python scripts/setup_google_auth.py` (option 2) to generate a new token that will never expire.
4. Update the `YOUTUBE_REFRESH_TOKEN` secret in GitHub.

## License

MIT
