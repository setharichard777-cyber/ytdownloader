import os
import yt_dlp
from pathlib import Path
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TOKEN") or "YOUR_BOT_TOKEN"

DOWNLOAD_DIR = "downloads"
Path(DOWNLOAD_DIR).mkdir(exist_ok=True)


def download_audio(url):
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{DOWNLOAD_DIR}/%(title)s.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "cookiefile": "cookies.txt",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file = ydl.prepare_filename(info)
        file = os.path.splitext(file)[0] + ".mp3"
        return file, info["title"]


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text

    msg = await update.message.reply_text("Downloading...")

    try:
        file, title = download_audio(url)

        await msg.edit_text("Uploading...")

        with open(file, "rb") as audio:
            await update.message.reply_audio(audio, title=title)

        os.remove(file)

    except Exception as e:
        await msg.edit_text(f"Failed: {e}")


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("Bot running")
    app.run_polling()


if __name__ == "__main__":
    main()