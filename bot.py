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

# ====================== CONFIG ======================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN environment variable is not set!")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ====================== REGEX ======================
YOUTUBE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)[\w-]+(?:[^\s]*)?"
)

# ====================== HELPERS ======================
def extract_url(text: str):
    match = YOUTUBE_RE.search(text.strip())
    return match.group(0) if match else None

def safe_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name[:70]

def ydl_base():
    base = {
        "quiet": True,
        "noplaylist": True,
        "concurrent_fragment_downloads": 32,
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "android", "web", "web_embedded_player"]
            }
        },
        "http_chunk_size": 10485760,
        "retries": 20,
        "fragment_retries": 20,
    }

    cookies_path = os.getenv("COOKIES_PATH", "/app/cookies.txt")
    if Path(cookies_path).exists():
        base["cookiefile"] = cookies_path
        log.info(f"Using cookies from: {cookies_path}")
    else:
        log.warning("No cookies file found → may hit 'Sign in to confirm you’re not a bot' error")

    return base

def fetch_info(url):
    with yt_dlp.YoutubeDL(ydl_base()) as ydl:
        return ydl.extract_info(url, download=False)

ARIA2_ARGS = "-x 32 -s 32 -k 10M --http-accept-gzip=true --file-allocation=none --summary-interval=0 --max-connection-per-server=32"

# ====================== DOWNLOAD FUNCTIONS ======================
def download_mp3(url):
    info = fetch_info(url)
    title = safe_filename(info["title"])
    path = DOWNLOAD_DIR / f"{title}.%(ext)s"

    opts = {
        **ydl_base(),
        "format": "bestaudio/best",
        "outtmpl": str(path),
        "external_downloader": "aria2c",
        "external_downloader_args": {"aria2c": ARIA2_ARGS},
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"}
        ],
        "writethumbnail": True
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    return DOWNLOAD_DIR / f"{title}.mp3"


def download_video(url, quality):
    info = fetch_info(url)
    title = safe_filename(info["title"])
    path = DOWNLOAD_DIR / f"{title}.%(ext)s"

    fmt = "bestvideo+bestaudio/best" if quality == "best" else f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"

    opts = {
        **ydl_base(),
        "format": fmt,
        "outtmpl": str(path),
        "external_downloader": "aria2c",
        "external_downloader_args": {"aria2c": ARIA2_ARGS},
        "merge_output_format": "mp4"
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    return DOWNLOAD_DIR / f"{title}.mp4"


# ====================== COMMANDS ======================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>Welcome to Ultra-Fast YouTube Downloader Bot!</b>\n\n"
        "🚀 What I can do:\n"
        "• Send any YouTube link (video or Shorts)\n"
        "• Choose MP3 or Video quality\n"
        "• Downloads at MAX speed (32 threads + aria2c)\n"
        "• Shows exact download time\n"
        "• Auto-deletes file after sending\n\n"
        "📌 Commands:\n"
        "/start — Show this welcome message\n"
        "/help  — Full instructions\n"
        "/ping  — Test if bot is alive\n\n"
        "Just paste a YouTube link and enjoy! ⚡\n\n"
        "<i>Note: Uses cookies to bypass YouTube restrictions on cloud servers.</i>",
        parse_mode="HTML"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Full Instructions</b>\n\n"
        "1. Paste any YouTube link\n"
        "2. Choose format:\n"
        "   🎵 MP3 (192kbps audio)\n"
        "   🎥 Best Video / 720p / 480p / 360p\n"
        "3. Wait a few seconds → file is sent + timer shown\n\n"
        "✅ Features:\n"
        "• Works with Shorts & normal videos\n"
        "• No ads, no limits on number of downloads\n"
        "• Telegram 50 MB limit (long videos = use 360p or MP3)\n"
        "• Auto cleanup\n\n"
        "⚡ Speed tip: cookies help a lot on Railway / VPS\n\n"
        "Need help? Just send a link or type /start",
        parse_mode="HTML"
    )


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong! Bot is alive and ready ⚡")


# ====================== MAIN HANDLERS ======================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = extract_url(update.message.text)
    if not url:
        await update.message.reply_text("❌ Please send a valid YouTube link only.\n\nType /start for instructions.")
        return

    context.user_data["url"] = url
    msg = await update.message.reply_text("🔍 Fetching video info...")

    loop = asyncio.get_running_loop()
    try:
        info = await loop.run_in_executor(None, fetch_info, url)
    except Exception as e:
        await msg.edit_text(f"❌ Could not fetch info:\n{str(e)[:200]}\n\nTry again or use a different video.")
        return

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
        [InlineKeyboardButton("🎵 MP3 (Audio)", callback_data="mp3")],
        [
            InlineKeyboardButton("🎥 Best Video", callback_data="video:best"),
            InlineKeyboardButton("720p", callback_data="video:720")
        ],
        [
            InlineKeyboardButton("480p", callback_data="video:480"),
            InlineKeyboardButton("360p", callback_data="video:360")
        ]
    ])

    await msg.edit_text(caption, reply_markup=keyboard)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    url = context.user_data.get("url")
    if not url:
        await query.edit_message_text("Session expired. Send the link again.")
        return

    await query.edit_message_text("🚀 Downloading at MAX speed (32 threads + aria2c)...")

    loop = asyncio.get_running_loop()
    file = None
    start_time = time.time()

    try:
        if query.data == "mp3":
            file = await loop.run_in_executor(None, download_mp3, url)
            with open(file, "rb") as f:
                await query.message.reply_audio(audio=f, title=file.stem)
        else:
            quality = query.data.split(":")[1]
            file = await loop.run_in_executor(None, download_video, url, quality)
            with open(file, "rb") as f:
                await query.message.reply_video(video=f, supports_streaming=True)

        download_time = round(time.time() - start_time, 1)
        await query.edit_message_text(f"✅ Done! Downloaded in **{download_time} seconds** ⚡")

    except Exception as e:
        log.error(e)
        await query.edit_message_text(f"❌ Failed: {str(e)[:180]}")
    finally:
        if file and file.exists():
            try:
                file.unlink()
            except:
                pass
        context.user_data.clear()


# ====================== MAIN ======================
def main():
    app = (
        Application.builder()
        .token(TOKEN)
        .read_timeout(600)
        .write_timeout(600)
        .connect_timeout(60)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping_command))

    # Message & Callback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("✅ COMPLETE BOT STARTED!")
    log.info("   • /start → Welcome & instructions")
    log.info("   • Send YouTube link → download menu")
    log.info("   • Using cookies: " + ("YES" if Path(os.getenv("COOKIES_PATH", "/app/cookies.txt")).exists() else "NO"))

    app.run_polling()


if __name__ == "__main__":
    main()