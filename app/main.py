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
from gemini_helpers import estimate_calorie_and_protein_targets


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
        - if yes:
            - ask_calories_target → numeric calories
            - ask_protein_target → numeric protein, then create profile
        - if no:
            - ask_weight → kg
            - ask_height → cm
            - ask_age → years
            - ask_goal → text; use Gemini to estimate targets and create profile
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
            context.user_data["registration_step"] = "ask_weight"

            await update.message.reply_text(
                "No problem at all 💪\n\n"
                "I’ll help you *calculate* good targets based on your stats.\n\n"
                "First, what’s your *weight in kg*?\n"
                "Example: `75`",
                parse_mode="Markdown",
            )
            return
        else:
            await update.message.reply_text(
                "Please reply with **yes** or **no** so I know whether you already have targets 😊",
                parse_mode="Markdown",
            )
            return

    # ----- PATH A: USER KNOWS TARGETS -----

    # Step 3A: Ask for calories target
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

    # Step 4A: Ask for protein target and create profile
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
            "Creating profile (manual targets) for chat_id=%s name=%s calories=%s protein=%s",
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
            "• Update your targets any time.\n\n"
            "Whenever you're ready, tell me about your next meal!",
            parse_mode="Markdown",
        )
        return

    # ----- PATH B: USER DOES NOT KNOW TARGETS (USE GEMINI) -----

    # Step 3B: Ask for weight
    if step == "ask_weight":
        try:
            weight = float(user_text)
        except ValueError:
            await update.message.reply_text(
                "I need a *number only* for your weight in kg 🔢\n" "Example: `75`",
                parse_mode="Markdown",
            )
            return

        data["weight_kg"] = weight
        context.user_data["registration_step"] = "ask_height"

        await update.message.reply_text(
            "Nice ⚖️\n\n" "What’s your *height in cm*?\n" "Example: `180`",
            parse_mode="Markdown",
        )
        return

    # Step 4B: Ask for height
    if step == "ask_height":
        try:
            height = float(user_text)
        except ValueError:
            await update.message.reply_text(
                "I need a *number only* for your height in cm 🔢\n" "Example: `180`",
                parse_mode="Markdown",
            )
            return

        data["height_cm"] = height
        context.user_data["registration_step"] = "ask_age"

        await update.message.reply_text(
            "Got it 📏\n\n" "How old are you (in *years*)?\n" "Example: `28`",
            parse_mode="Markdown",
        )
        return

    # Step 5B: Ask for age
    if step == "ask_age":
        try:
            age = int(user_text)
        except ValueError:
            await update.message.reply_text(
                "I need a *whole number* for your age in years 🔢\n" "Example: `28`",
                parse_mode="Markdown",
            )
            return

        data["age_years"] = age
        context.user_data["registration_step"] = "ask_goal"

        await update.message.reply_text(
            "Perfect 🎯\n\n"
            "Finally, what’s your main goal?\n"
            "You can say things like:\n"
            "• gain muscle\n"
            "• lose fat\n"
            "• maintain\n",
            parse_mode="Markdown",
        )
        return

    # Step 6B: Ask for goal, call Gemini, create profile
    if step == "ask_goal":
        goal_text = user_text.lower()
        data["goal_raw"] = goal_text

        # Normalize the goal into one of three categories for the prompt
        if "gain" in goal_text or "bulk" in goal_text or "muscle" in goal_text:
            goal_norm = "gain muscle"
        elif "lose" in goal_text or "cut" in goal_text or "fat" in goal_text:
            goal_norm = "lose fat"
        else:
            goal_norm = "maintain"

        weight = float(data["weight_kg"])
        height = float(data["height_cm"])
        age = int(data["age_years"])

        await update.message.reply_text(
            "Love that goal 🙌\n\n"
            "Give me a second while I calculate smart daily targets for you… 🤖",
            parse_mode="Markdown",
        )

        # Ask Gemini for calorie & protein targets
        calories_target, protein_target = estimate_calorie_and_protein_targets(
            weight_kg=weight,
            height_cm=height,
            age_years=age,
            goal=goal_norm,
        )

        name = data.get("name", "champ")

        logger.info(
            "Creating profile (Gemini targets) for chat_id=%s name=%s "
            "weight=%.2f height=%.2f age=%d goal=%s calories=%.2f protein=%.2f",
            chat_id,
            name,
            weight,
            height,
            age,
            goal_norm,
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
            "Targets calculated and locked in, legend 💪\n\n"
            f"Here’s what I recommend based on your stats and goal:\n"
            f"🔥 *{int(calories_target)}* kcal per day\n"
            f"🍗 *{int(protein_target)}* g protein per day\n\n"
            "From now on you can:\n"
            "• Send me meal descriptions or photos to log your food 🥗\n"
            "• Ask for a *daily report* to see your progress 📊\n"
            "• Update your targets any time as things change.\n\n"
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
