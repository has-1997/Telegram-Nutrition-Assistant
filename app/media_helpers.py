# media_helpers.py

import os
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

# Folder where we'll save downloaded media files
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)


async def download_voice_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[str]:
    """
    Inputs:
        update: Telegram update containing a voice message.
        context: gives us access to the bot for downloading.
    Returns:
        The local file path (string) of the saved voice file,
        or None if something went wrong.
    Purpose:
        Download the user's voice message to our local 'downloads' folder.
    """
    if update.message is None or update.message.voice is None:
        return None

    voice = update.message.voice
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    # Example filename: downloads/voice_123456789_42.ogg
    filename = DOWNLOAD_DIR / f"voice_{chat_id}_{message_id}.ogg"

    try:
        tg_file = await context.bot.get_file(voice.file_id)
        await tg_file.download_to_drive(custom_path=str(filename))
        return str(filename)
    except Exception as e:
        # In a real app you might log this; for now we just print.
        print("Error downloading voice file:", e)
        return None


async def download_photo_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[str]:
    """
    Inputs:
        update: Telegram update containing a photo.
        context: gives us access to the bot for downloading.
    Returns:
        The local file path (string) of the saved photo file,
        or None if something went wrong.
    Purpose:
        Download the *highest resolution* version of the user's photo
        to our local 'downloads' folder.
    """
    if update.message is None or not update.message.photo:
        return None

    # Telegram sends multiple sizes; the last one is the biggest
    photo_size = update.message.photo[-1]
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    # We'll default to .jpg – Telegram usually uses JPEG for photos
    filename = DOWNLOAD_DIR / f"photo_{chat_id}_{message_id}.jpg"

    try:
        tg_file = await context.bot.get_file(photo_size.file_id)
        await tg_file.download_to_drive(custom_path=str(filename))
        return str(filename)
    except Exception as e:
        print("Error downloading photo file:", e)
        return None
