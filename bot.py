import os
import re
import asyncio
import logging
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


TOKEN = os.getenv("TOKEN")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


YOUTUBE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)[\w-]+"
)


def extract_url(text: str):
    m = YOUTUBE_RE.search(text)
    return m.group(0) if m else None


def safe_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name[:80]


def ydl_base():
    return {
        "quiet": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "retries": 10,
        "fragment_retries": 10,
    }


def fetch_info(url):
    opts = ydl_base()
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def download_mp3(url, info):
    title = safe_filename(info["title"])
    path = DOWNLOAD_DIR / f"{title}.%(ext)s"

    opts = {
        **ydl_base(),
        "format": "bestaudio/best",
        "outtmpl": str(path),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    return DOWNLOAD_DIR / f"{title}.mp3"


def download_video(url, info):
    title = safe_filename(info["title"])
    path = DOWNLOAD_DIR / f"{title}.%(ext)s"

    opts = {
        **ydl_base(),
        "format": "best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(path),
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    return DOWNLOAD_DIR / f"{title}.mp4"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send YouTube link")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    url = extract_url(update.message.text)

    if not url:
        await update.message.reply_text("Invalid link")
        return

    msg = await update.message.reply_text("Getting video info...")

    loop = asyncio.get_running_loop()

    try:
        info = await loop.run_in_executor(None, fetch_info, url)
    except Exception:
        await msg.edit_text("Failed to fetch video info")
        return

    context.user_data["url"] = url
    context.user_data["info"] = info

    title = info.get("title", "video")
    duration = info.get("duration", 0)

    m, s = divmod(duration, 60)

    text = f"{title}\n{m}:{s:02d}\n\nChoose format"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("MP3", callback_data="mp3")],
        [InlineKeyboardButton("Video", callback_data="video")]
    ])

    await msg.edit_text(text, reply_markup=keyboard)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    url = context.user_data.get("url")
    info = context.user_data.get("info")

    if not url:
        await query.edit_message_text("Send link again")
        return

    await query.edit_message_text("Downloading...")

    loop = asyncio.get_running_loop()
    file = None

    try:

        if query.data == "mp3":

            file = await loop.run_in_executor(None, download_mp3, url, info)

            with open(file, "rb") as f:
                await query.message.reply_audio(audio=f)

        else:

            file = await loop.run_in_executor(None, download_video, url, info)

            with open(file, "rb") as f:
                await query.message.reply_video(video=f, supports_streaming=True)

        await query.edit_message_text("Done")

    except Exception as e:

        log.exception(e)
        await query.edit_message_text("Download failed")

    finally:

        if file and Path(file).exists():
            Path(file).unlink()

        context.user_data.clear()


def main():

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("Bot started")

    app.run_polling()


if __name__ == "__main__":
    main()