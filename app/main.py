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

from sheets_helpers import get_profile_by_user_id  # our Google Sheets helper


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
    Behavior:
        - When user sends /start, check if they already have a profile.
        - If not, send them into the registration flow.
        - If yes, greet them as a returning athlete.
    """
    chat_id = update.effective_chat.id
    logger.info("Received /start from chat_id=%s", chat_id)

    profile = get_profile_by_user_id(chat_id)

    if profile is None:
        # New user: invite them to register
        await update.message.reply_text(
            "🔥 Welcome to *Cal AI* – your nutrition assistant!\n\n"
            "Looks like this is your first time here.\n"
            "Let’s set up your profile so I can coach you properly.\n\n"
            "First question: what’s your *first name*, champ? 💪",
            parse_mode="Markdown",
        )
        # Mark that we're in registration mode for this user
        context.user_data["mode"] = "registration"
        context.user_data["registration_step"] = "ask_name"
    else:
        # Returning user: greet them with their name if we have it
        name = profile.get("Name") or "champ"
        await update.message.reply_text(
            f"Welcome back, *{name}* 💪\n\n"
            "You’re already registered. Tell me about your meals or ask for a daily report.",
            parse_mode="Markdown",
        )
        context.user_data["mode"] = "main"


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Behavior:
        - Runs for every non-command text message.
        - Looks up the user in the Profile sheet.
        - Routes to either the registration assistant or the main nutrition agent.
    """
    if update.message is None:
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    logger.info("Received text from chat_id=%s: %s", chat_id, user_text)

    profile = get_profile_by_user_id(chat_id)

    if profile is None:
        # Green zone: not registered yet → go to registration assistant
        context.user_data.setdefault("mode", "registration")
        await registration_assistant(update, context)
    else:
        # Green zone: already registered → go to main nutrition agent
        context.user_data["mode"] = "main"
        await main_nutrition_agent(update, context, profile)


async def registration_assistant(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Temporary placeholder.
    Behavior now:
        - Just confirms we’re in the registration side.
    Later:
        - We’ll expand this to ask name, goals, targets, etc.,
          and write to the Profile sheet.
    """
    await update.message.reply_text(
        "🧾 Registration assistant here.\n\n"
        "We’ll soon ask your name and nutrition goals and save them.\n"
        "For now, this is just a placeholder so routing works.",
    )


async def main_nutrition_agent(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    profile: dict,
) -> None:
    """
    Temporary placeholder.
    Behavior now:
        - Confirms we’re in the main nutrition side.
    Later:
        - Will log meals, update targets, and show daily reports.
    """
    name = profile.get("Name") or "champ"
    await update.message.reply_text(
        f"🏋️ Main nutrition coach here, *{name}*.\n\n"
        "Soon I’ll log meals, update your targets, and show daily reports.\n"
        "For now, this is just a placeholder reply.",
        parse_mode="Markdown",
    )


def main() -> None:
    """
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
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

    print("✅ Cal AI bot is running with basic routing.")
    application.run_polling()


# This runs when you do: python main.py
if __name__ == "__main__":
    main()
