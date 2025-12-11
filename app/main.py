# main.py

import os
import logging
from typing import Dict, Any

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from sheets_helpers import (
    get_profile_by_user_id,
    create_profile,
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
        context.user_data.clear()
        context.user_data["mode"] = "registration"
        context.user_data["registration_step"] = "ask_name"
        context.user_data["registration_data"] = {}

        await update.message.reply_text(
            "🔥 Welcome to *Cal AI* – your nutrition assistant!\n\n"
            "Looks like this is your first time here.\n"
            "Let’s set up your profile so I can coach you properly.\n\n"
            "First question: what’s your *first name*, champ? 💪",
            parse_mode="Markdown",
        )
    else:
        # Returning user: greet them with their name if we have it
        name = profile.get("Name") or "champ"
        context.user_data.clear()
        context.user_data["mode"] = "main"

        await update.message.reply_text(
            f"Welcome back, *{name}* 💪\n\n"
            "You’re already registered. Tell me about your meals or ask for a daily report.",
            parse_mode="Markdown",
        )


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
    user_text = (update.message.text or "").strip()
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
    Behavior:
        Step-based registration flow:
        - ask_name → store name
        - ask_know_targets → do they already know calories/protein?
        - ask_calories_target → numeric calories
        - ask_protein_target → numeric protein, then create profile
    """
    if update.message is None:
        return

    chat_id = update.effective_chat.id
    user_text = (update.message.text or "").strip()
    data: Dict[str, Any] = context.user_data.setdefault("registration_data", {})
    step = context.user_data.get("registration_step", "ask_name")

    # Step 1: Ask for name
    if step == "ask_name":
        data["name"] = user_text
        context.user_data["registration_step"] = "ask_know_targets"

        await update.message.reply_text(
            f"Nice to meet you, {data['name']} 😎\n\n"
            "Do you already know your daily *calorie* and *protein* targets?\n"
            "Reply with **yes** or **no**.",
            parse_mode="Markdown",
        )

        return

    # Step 2: Ask if they know their targets
    if step == "ask_know_targets":
        text_lower = user_text.lower()
        if text_lower in {"yes", "y", "yeah", "yep", "sure"}:
            data["knows_targets"] = True
            context.user_data["registration_step"] = "ask_calories_target"

            await update.message.reply_text(
                "Awesome 🔥\n\n"
                "Please send your *daily calorie target* as a **number only**.\n"
                "Example: `2200`",
                parse_mode="Markdown",
            )
            return
        elif text_lower in {"no", "n", "nope", "nah"}:
            data["knows_targets"] = False
            # We'll handle the 'I don't know' path with Gemini later
            await update.message.reply_text(
                "No problem at all 💪\n\n"
                "In a later step I’ll help you *calculate* good targets based on your stats.\n"
                "For now, please answer as if you **do** know them so we can finish wiring the flow.\n\n"
                "So, pretend you have a number and send your *daily calorie target* as a **number only**.\n"
                "Example: `2200`",
                parse_mode="Markdown",
            )
            context.user_data["registration_step"] = "ask_calories_target"
            return
        else:
            await update.message.reply_text(
                "Please reply with **yes** or **no** so I know whether you already have targets 😊",
                parse_mode="Markdown",
            )
            return

    # Step 3: Ask for calories target
    if step == "ask_calories_target":
        try:
            calories = float(user_text)
        except ValueError:
            await update.message.reply_text(
                "I need a *number only* for calories, champ 🔢\n" "Example: `2200`",
                parse_mode="Markdown",
            )
            return

        data["calories_target"] = calories
        context.user_data["registration_step"] = "ask_protein_target"

        await update.message.reply_text(
            "Got it 🔥\n\n"
            "Now send your *daily protein target* in grams as a **number only**.\n"
            "Example: `150`",
            parse_mode="Markdown",
        )
        return

    # Step 4: Ask for protein target and create profile
    if step == "ask_protein_target":
        try:
            protein = float(user_text)
        except ValueError:
            await update.message.reply_text(
                "I need a *number only* for protein, in grams 🔢\n" "Example: `150`",
                parse_mode="Markdown",
            )
            return

        data["protein_target"] = protein

        # Create the profile row in Google Sheets
        name = data.get("name", "champ")
        calories_target = data["calories_target"]
        protein_target = data["protein_target"]

        logger.info(
            "Creating profile for chat_id=%s name=%s calories=%s protein=%s",
            chat_id,
            name,
            calories_target,
            protein_target,
        )

        create_profile(
            user_id=chat_id,
            name=name,
            calories_target=calories_target,
            protein_target=protein_target,
        )

        # Clear registration state & switch to main mode
        context.user_data.clear()
        context.user_data["mode"] = "main"

        await update.message.reply_text(
            "Awesome, champ 💪\n\n"
            f"Your nutrition targets are locked in:\n"
            f"🔥 *{int(calories_target)}* kcal\n"
            f"🍗 *{int(protein_target)}* g protein\n\n"
            "From now on you can:\n"
            "• Send me meal descriptions or photos to log your food 🥗\n"
            "• Ask for a *daily report* to see your progress 📊\n"
            "• Later, we’ll let you update your targets any time.\n\n"
            "Whenever you're ready, tell me about your next meal!",
            parse_mode="Markdown",
        )
        
        return


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
