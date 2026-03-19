import os
import re
import asyncio
import logging
import time
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

import yt_dlp

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("TOKEN environment variable not set")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ================= REGEX =================
YOUTUBE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)[\w-]+(?:[^\s]*)?"
)

# ================= HELPERS =================
def extract_url(text: str):
    match = YOUTUBE_RE.search(text.strip())
    return match.group(0) if match else None

def safe_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name[:70]

def ydl_base():
    return {
        "quiet": True,
        "nocheckcertificate": True,
        "cookiefile": "cookies.txt",
        "socket_timeout": 60,
        "noplaylist": True,
    }

def fetch_info(url):
    with yt_dlp.YoutubeDL(ydl_base()) as ydl:
        return ydl.extract_info(url, download=False)

# ================= DOWNLOAD =================
def download_mp3(url, info):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    title = safe_filename(info["title"])
    path = DOWNLOAD_DIR / f"{title}.mp3"
    opts = {
        **ydl_base(),
        "format": "bestaudio/best",
        "outtmpl": str(path),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"},
        ],
        "writethumbnail": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    return path

def download_video(url, quality, info):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    title = safe_filename(info["title"])
    path = DOWNLOAD_DIR / f"{title}.mp4"
    fmt = "bestvideo+bestaudio/best" if quality == "best" else f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
    opts = {
        **ydl_base(),
        "format": fmt,
        "outtmpl": str(path),
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    return path

# ================= COMMANDS =================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send a YouTube link.\nChoose MP3 or video quality.\nFast download enabled."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "1. Send a YouTube link\n"
        "2. Choose MP3 or video quality\n"
        "3. Bot downloads and sends file\n\n"
        "Files auto-delete after sending."
    )

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong! Bot is alive.")

# ================= MESSAGE HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = extract_url(update.message.text)
    if not url:
        await update.message.reply_text("❌ Send a valid YouTube link")
        return

    msg = await update.message.reply_text("🔍 Fetching video info...")
    loop = asyncio.get_running_loop()

    try:
        info = await loop.run_in_executor(None, fetch_info, url)
    except Exception as e:
        await msg.edit_text("❌ Failed to fetch video info")
        log.exception("yt-dlp error")
        return

    context.user_data["url"] = url
    context.user_data["info"] = info

    title = info.get("title", "Unknown")
    duration = info.get("duration", 0)
    uploader = info.get("uploader", "Unknown")
    m, s = divmod(duration, 60)

    caption = f"""
📌 {title}
👤 {uploader}
⏱ {m}:{s:02d}

Choose format:
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 MP3", callback_data="mp3")],
        [InlineKeyboardButton("🎥 Best", callback_data="video:best"), InlineKeyboardButton("720p", callback_data="video:720")],
        [InlineKeyboardButton("480p", callback_data="video:480"), InlineKeyboardButton("360p", callback_data="video:360")]
    ])

    await msg.edit_text(caption, reply_markup=keyboard)

# ================= CALLBACK HANDLER =================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    url = context.user_data.get("url")
    info = context.user_data.get("info")
    if not url or not info:
        await query.edit_message_text("❌ Session expired. Send link again.")
        return

    await query.edit_message_text("⚡ Downloading...")

    loop = asyncio.get_running_loop()
    start_time = time.time()
    file = None

    try:
        if query.data == "mp3":
            file = await loop.run_in_executor(None, download_mp3, url, info)
            with open(file, "rb") as f:
                await query.message.reply_audio(audio=f, title=file.stem)
        else:
            quality = query.data.split(":")[1]
            file = await loop.run_in_executor(None, download_video, url, quality, info)
            with open(file, "rb") as f:
                await query.message.reply_video(video=f, supports_streaming=True)

        t = round(time.time() - start_time, 1)
        await query.edit_message_text(f"✅ Done! Downloaded in {t} seconds ⚡")

    except Exception as e:
        log.exception("yt-dlp error")
        await query.edit_message_text(f"❌ Failed: {str(e)[:120]}")
    finally:
        if file and file.exists():
            try:
                file.unlink()
            except:
                pass
        context.user_data.clear()

# ================= MAIN =================
def main():
    app = (
        Application.builder()
        .token(TOKEN)
        .read_timeout(600)
        .write_timeout(600)
        .connect_timeout(60)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping_command))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("✅ Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
