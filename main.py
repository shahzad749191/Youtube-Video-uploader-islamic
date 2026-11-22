#!/usr/bin/env python3
"""
YouTube Shorts Automation Bot (Forced PKT Timezone, Clean Temp Folder)
"""

import os
import sys
import json
import random
import pickle
import logging
import time
import datetime
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo # NEW: For Pakistan Time

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

try:
    from moviepy import (ImageClip, AudioFileClip,
                         concatenate_videoclips, concatenate_audioclips)
    MOVIEPY_V2 = True
except ImportError:
    from moviepy.editor import (ImageClip, AudioFileClip,
                                concatenate_videoclips, concatenate_audioclips)
    MOVIEPY_V2 = False

# ============================================================
# Paths & Logging
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
IMAGES_DIR = ASSETS_DIR / "images"
TOKENS_DIR = BASE_DIR / "tokens"
TEMP_DIR = BASE_DIR / "temp_videos"
LOGS_DIR = BASE_DIR / "logs"
MUSIC_FILE = ASSETS_DIR / "music.mp3"
CONFIG_FILE = BASE_DIR / "config.json"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"

# Set Timezone to Pakistan
PKT = ZoneInfo("Asia/Karachi")

for d in (ASSETS_DIR, IMAGES_DIR, TOKENS_DIR, TEMP_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.FileHandler(LOGS_DIR / "bot.log", encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("shorts-bot")

# ============================================================
# Config
# ============================================================
def load_config():
    if not CONFIG_FILE.exists():
        log.error("config.json not found!")
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

def get_safe_filename(channel_name):
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', channel_name)

def clean_temp_folder():
    if TEMP_DIR.exists():
        for file in TEMP_DIR.iterdir():
            try:
                if file.is_file(): file.unlink()
                elif file.is_dir(): shutil.rmtree(file)
            except Exception as e:
                log.warning(f"Could not delete {file}: {e}")
        log.info("Temp folder cleaned.")

# ============================================================
# Image Management
# ============================================================
def list_images():
    valid_extensions = (".jpg", ".jpeg", ".png", ".jfif", ".webp")
    return sorted(f.name for f in IMAGES_DIR.iterdir()
                  if f.suffix.lower() in valid_extensions)

def select_images(pool, count):
    if len(pool) < count:
        raise ValueError(f"Not enough images. You have {len(pool)}, but need {count}.")
    shuffled = list(pool)
    random.shuffle(shuffled)
    picked = shuffled[:count]
    log.info(f"Selected images: {picked}")
    return picked

# ============================================================
# Video
# ============================================================
def _dur(c, d): return c.with_duration(d) if MOVIEPY_V2 else c.set_duration(d)
def _res(c, **k): return c.resized(**k) if MOVIEPY_V2 else c.resize(**k)
def _crop(c, **k): return c.cropped(**k) if MOVIEPY_V2 else c.crop(**k)
def _pos(c, p): return c.with_position(p) if MOVIEPY_V2 else c.set_position(p)
def _aud(c, a): return c.with_audio(a) if MOVIEPY_V2 else c.set_audio(a)
def _sub(c, a, b): return c.subclipped(a, b) if MOVIEPY_V2 else c.subclip(a, b)

def create_video(image_names, music_path, output_path, per_image=2.4):
    log.info(f"Building video: {len(image_names)} images × {per_image}s")
    clips = []
    
    TARGET_W = 1080
    TARGET_H = 1920

    for name in image_names:
        path = IMAGES_DIR / name
        if not path.exists(): continue
        c = ImageClip(str(path))
        c = _dur(c, per_image)
        c = _res(c, height=TARGET_H)
        if c.w < TARGET_W: c = _res(c, width=TARGET_W)
        c = _crop(c, x_center=c.w/2, y_center=c.h/2, width=TARGET_W, height=TARGET_H)
        c = _pos(c, "center")
        clips.append(c)

    if not clips: raise RuntimeError("No valid image clips found.")
    video = concatenate_videoclips(clips, method="compose")

    if Path(music_path).exists():
        base = AudioFileClip(music_path)
        loops = max(1, int(video.duration / base.duration) + 1)
        parts = [AudioFileClip(music_path) for _ in range(loops)]
        looped = concatenate_audioclips(parts)
        looped = _sub(looped, 0, video.duration)
        final = _aud(video, looped)
        log.info("Background music attached.")
    else:
        final = video

    log.info("Rendering MP4...")
    temp_audio = str(TEMP_DIR / f"temp_audio_{int(time.time())}.m4a")
    
    final.write_videofile(
        str(output_path), fps=24, codec="libx264", audio_codec="aac",
        preset="veryfast", threads=2, logger=None,
        temp_audiofile=temp_audio, remove_temp=True
    )
    log.info(f"Video written: {output_path}")

    try:
        final.close(); video.close()
        for c in clips: c.close()
    except Exception: pass
    return output_path

# ============================================================
# Console OAuth Logic
# ============================================================
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
REDIRECT_URI = "http://localhost:8080/"

def _console_oauth(channel_name):
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRETS_FILE), SCOPES, redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

    print("\n" + "=" * 74)
    print(f"  LINKING NEW CHANNEL: {channel_name.upper()}")
    print("=" * 74)
    print("\nSTEP 1: Open this URL in your browser:\n")
    print(f"   {auth_url}\n")
    print("STEP 2: Log in with the Google account for this channel.")
    print("        (Make sure this Gmail is added to 'Test Users' in Google Cloud!)")
    print("\nSTEP 3: Your browser will fail to load (localhost:8080). NORMAL.")
    print("        Copy the ENTIRE broken URL from your address bar.")
    print("\nSTEP 4: Right-click here in this console, PASTE the URL, and press Enter.")
    print("=" * 74 + "\n")

    try:
        pasted_url = input("Paste full redirect URL here: ").strip()
        code = None
        if pasted_url.startswith("http"):
            q = parse_qs(urlparse(pasted_url).query)
            code = q.get("code", [None])[0]
        elif pasted_url.startswith("4/"):
            code = pasted_url

        if not code: raise ValueError("Could not find the authorization code.")
        flow.fetch_token(code=code)
        log.info(f"[{channel_name}] ✅ OAuth successful!")
        return flow.credentials
    except Exception as e:
        log.error(f"[{channel_name}] OAuth failed: {e}")
        raise RuntimeError("OAuth failed")

def get_youtube_service(channel_name):
    safe_name = get_safe_filename(channel_name)
    token_file = TOKENS_DIR / f"token_{safe_name}.pickle"
    
    creds = None
    if token_file.exists():
        with open(token_file, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info(f"[{channel_name}] Refreshing credentials...")
            creds.refresh(Request())
        else:
            creds = _console_oauth(channel_name)
        with open(token_file, "wb") as f:
            pickle.dump(creds, f)
        log.info(f"[{channel_name}] Token saved to tokens/{token_file.name}")
    
    return build("youtube", "v3", credentials=creds)

# ============================================================
# Upload
# ============================================================
def upload_video(video_path, config, channel_name):
    log.info(f"[{channel_name}] Uploading: {video_path}")
    yt = get_youtube_service(channel_name)
    
    yt_config = config.get("youtube", {})
    title = yt_config.get("title_prefix", "#Allah")
    caption = yt_config.get("caption", "#Allah")
    privacy = yt_config.get("privacy_status", "public")
    kids = yt_config.get("made_for_kids", False)

    body = {
        "snippet": {
            "title": title,
            "description": caption,
            "tags": ["#Allah", "Shorts", "Islamic"],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": kids,
        },
    }
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            log.info(f"  [{channel_name}] Upload: {int(status.progress() * 100)}%")
    log.info(f"[{channel_name}] Upload complete! Video ID: {resp['id']}")
    return resp

# ============================================================
# Main Run
# ============================================================
def run_bot():
    log.info("=" * 70)
    log.info("BOT RUN START")
    log.info("=" * 70)
    try:
        clean_temp_folder() 
        
        config = load_config()
        pool = list_images()
        
        images_needed = config.get("images_per_video", 5)
        duration = config.get("video_duration_per_image", 2.4)
        
        if len(pool) < images_needed:
            log.error(f"Not enough images. Have {len(pool)}, need {images_needed}.")
            return

        for ch_name in config.get("youtube", {}).get("channels", []):
            safe_name = get_safe_filename(ch_name)
            log.info(f"--- Processing for: {ch_name} ---")
            
            selected = select_images(pool, images_needed)
            out_file = TEMP_DIR / f"short_{safe_name}_{int(time.time())}.mp4"
            
            create_video(selected, str(MUSIC_FILE), str(out_file), duration)
            
            try:
                upload_video(str(out_file), config, ch_name)
            except Exception as e:
                log.error(f"Failed to upload to {ch_name}: {e}")
            finally:
                if out_file.exists():
                    out_file.unlink()
                    log.info(f"Temp video removed.")
                    
        log.info("BOT RUN COMPLETE ✅")
    except Exception:
        log.exception("BOT RUN FAILED")
    finally:
        log.info("=" * 70)

# ============================================================
# Scheduler & Entry
# ============================================================
def setup_schedule(config):
    times = config.get("schedule_times", ["08:00", "10:00", "14:00"])
    log.info(f"Scheduler active (Pakistan Time). Runs at: {times}")
    last_run = {}
    while True:
        try:
            # GET PAKISTAN TIME
            now = datetime.datetime.now(PKT)
            hhmm = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")
            
            if hhmm in times and last_run.get(hhmm) != today:
                log.info(f"Scheduled trigger fired at {hhmm} PKT")
                run_bot()
                last_run[hhmm] = today
            time.sleep(20)
        except Exception:
            log.exception("Scheduler-level error (continuing)")
            time.sleep(60)

if __name__ == "__main__":
    log.info("Bot booting...")
    clean_temp_folder()
    
    config = load_config()

    for ch_name in config.get("youtube", {}).get("channels", []):
        safe_name = get_safe_filename(ch_name)
        token_path = TOKENS_DIR / f"token_{safe_name}.pickle"
        
        if not token_path.exists():
            log.info(f"No login found for '{ch_name}'. Triggering OAuth...")
            try:
                get_youtube_service(ch_name)
            except Exception as e:
                log.error(f"Could not link {ch_name}. Skipping.")

    log.info("Startup checks complete ✅")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        run_bot()
    else:
        setup_schedule(config)
