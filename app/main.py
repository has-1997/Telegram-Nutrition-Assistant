# main.py

import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Set up basic logging so we can see what's happening in the terminal
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Load variables from the .env file
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Inputs:
        update: message info from Telegram (who, what, where)
        context: extra data from the bot framework
    Returns:
        nothing (we just send a reply)
    Behavior:
        Greets the user when they send /start.
    """
    chat_id = update.effective_chat.id
    logger.info("Received /start from chat_id=%s", chat_id)

    await update.message.reply_text(
        "🔥 Welcome to *Cal AI* – your nutrition assistant!\n\n"
        "For now I just echo your messages while we wire things up. 💪",
        parse_mode="Markdown",
    )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Inputs:
        update: text message from the user
        context: extra bot info
    Returns:
        nothing (we reply to the user)
    Behavior:
        Simply repeats what the user typed (for testing).
    """
    user_text = update.message.text
    chat_id = update.effective_chat.id
    logger.info("Echoing message from chat_id=%s: %s", chat_id, user_text)

    await update.message.reply_text(f"You said: {user_text}")


# This will become our main entry point for the bot
def main() -> None:
    """
    Inputs: none.
    Returns: none.
    Behavior:
        - Checks for the bot token
        - Creates the Telegram application
        - Registers handlers
        - Starts long polling (listening for messages)
    """
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from your .env file")

    # Build the bot application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register the /start command handler
    application.add_handler(CommandHandler("start", start))

    # Register a handler for all plain text messages (that are not commands)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    print("✅ Cal AI bot is running. Go to Telegram and send /start to your bot.")
    # Start listening for updates from Telegram
    application.run_polling()


# This runs when you do: python main.py
if __name__ == "__main__":
    main()
