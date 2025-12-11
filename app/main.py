# main.py

import os
import logging
from typing import Dict, Any
from datetime import datetime

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
    append_meal_row,
)
from gemini_helpers import (
    estimate_calorie_and_protein_targets,
    transcribe_voice_message,
    analyze_meal_image,
)
from media_helpers import (
    download_voice_file,
    download_photo_file,
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


def today_str() -> str:
    """
    Inputs: none.
    Returns: today's date as 'YYYY-MM-DD'.
    Purpose: use a consistent date format for meal logging.
    """
    return datetime.utcnow().strftime("%Y-%m-%d")


# --------------------- COMMAND HANDLER ---------------------


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
            "You’re already registered.\n"
            "Send me meal descriptions, photos, or voice messages, "
            "or ask for a daily report.",
            parse_mode="Markdown",
        )


# --------------------- TEXT ROUTING ---------------------


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
    logger.info("Received TEXT from chat_id=%s: %s", chat_id, user_text)

    profile = get_profile_by_user_id(chat_id)

    if profile is None:
        # Not registered yet → go to registration assistant
        context.user_data.setdefault("mode", "registration")
        await registration_assistant(update, context)
    else:
        # Already registered → go to main nutrition agent
        context.user_data["mode"] = "main"
        await main_nutrition_agent(update, context, profile, user_text)


# --------------------- VOICE ROUTING (with Gemini) ---------------------


async def handle_voice_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Behavior:
        - Runs when the user sends a voice message.
        - If not registered → ask them to run /start.
        - If registered:
            - Download the audio file.
            - Send it to Gemini to get a text transcription.
            - Pass that text to the main nutrition agent as if user typed it.
    """
    if update.message is None:
        return

    chat_id = update.effective_chat.id
    logger.info("Received VOICE from chat_id=%s", chat_id)

    profile = get_profile_by_user_id(chat_id)

    if profile is None:
        await update.message.reply_text(
            "Hey legend 👋\n\n"
            "Before I can understand your voice messages, "
            "I need to know who you are.\n"
            "Please send /start and complete the quick setup first 💪",
        )
        return

    # Download the voice note locally
    local_path = await download_voice_file(update, context)
    if local_path is None:
        await update.message.reply_text(
            "It was not possible to process the file. "
            "File type not supported or download failed 😕",
        )
        return

    # Ask Gemini to turn audio into text
    try:
        transcribed_text = transcribe_voice_message(
            audio_path=local_path,
            mime_type="audio/ogg",
        )
    except Exception as e:
        logger.exception("Error while transcribing voice message: %s", e)
        await update.message.reply_text(
            "Something went wrong while processing your voice message 😔\n"
            "Please try again, or send it as text instead.",
        )
        return

    if not transcribed_text.strip():
        await update.message.reply_text(
            "I couldn’t understand that voice message clearly 😕\n"
            "Could you repeat it or send it as text?",
        )
        return

    # Now treat the transcribed text just like a normal message
    logger.info(
        "Transcribed VOICE from chat_id=%s into TEXT: %s",
        chat_id,
        transcribed_text,
    )
    context.user_data["mode"] = "main"
    await main_nutrition_agent(update, context, profile, transcribed_text)


# --------------------- PHOTO ROUTING (with Gemini meal analysis) ---------------------


async def handle_photo_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Behavior:
        - Runs when the user sends a photo.
        - If not registered → ask them to run /start.
        - If registered:
            - Download the photo.
            - Ask Gemini to analyze the meal and estimate macros.
            - Log a new row in the Meals sheet for today.
            - Reply with a summary of what was logged.
    """
    if update.message is None:
        return

    chat_id = update.effective_chat.id
    logger.info("Received PHOTO from chat_id=%s", chat_id)

    profile = get_profile_by_user_id(chat_id)

    if profile is None:
        await update.message.reply_text(
            "Hey champ 📸\n\n"
            "Before I can analyze your food photos, "
            "I need to set up your profile.\n"
            "Please send /start and complete the quick setup first 💪",
        )
        return

    # 1) Download the photo locally
    local_path = await download_photo_file(update, context)
    if local_path is None:
        await update.message.reply_text(
            "It was not possible to process the file. "
            "File type not supported or download failed 😕",
        )
        return

    # 2) Ask Gemini to analyze the image
    try:
        analysis = analyze_meal_image(
            image_path=local_path,
            mime_type="image/jpeg",  # Telegram photos are usually JPEG
        )
    except Exception as e:
        logger.exception("Error while analyzing meal image: %s", e)
        await update.message.reply_text(
            "Something went wrong while analyzing that meal photo 😔\n"
            "Please try again, or describe the meal in text.",
        )
        return

    meal_description = analysis.get("meal_description", "Meal")
    calories = float(analysis.get("calories", 0))
    proteins = float(analysis.get("proteins", 0))
    carbs = float(analysis.get("carbs", 0))
    fats = float(analysis.get("fats", 0))

    # 3) Log the meal in the Meals sheet with today's date
    date_str = today_str()
    logger.info(
        "Logging meal from photo for chat_id=%s on %s: %s (kcal=%.1f, P=%.1f, C=%.1f, F=%.1f)",
        chat_id,
        date_str,
        meal_description,
        calories,
        proteins,
        carbs,
        fats,
    )

    try:
        append_meal_row(
            user_id=chat_id,
            date_str=date_str,
            meal_description=meal_description,
            calories=calories,
            proteins=proteins,
            carbs=carbs,
            fats=fats,
        )
    except Exception as e:
        logger.exception("Error while appending meal row: %s", e)
        await update.message.reply_text(
            "I analyzed your meal, but something went wrong while saving it 😔\n"
            "Please try again in a moment.",
        )
        return

    # 4) Reply to the user with a friendly summary
    reply_text = (
        "🍽 Meal logged from your photo!\n\n"
        f"Description: {meal_description}\n"
        f"🔥 Calories: ~{int(calories)} kcal\n"
        f"🍗 Protein: ~{int(proteins)} g\n"
        f"🍞 Carbs: ~{int(carbs)} g\n"
        f"🥑 Fats: ~{int(fats)} g\n\n"
        "I’ve added this to today’s log.\n"
        "You can ask me for a *daily report* any time to see your totals 📊"
    )

    await update.message.reply_text(reply_text, parse_mode="Markdown")


# --------------------- REGISTRATION ASSISTANT ---------------------


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


# --------------------- MAIN NUTRITION AGENT (still simple) ---------------------


async def main_nutrition_agent(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    profile: dict,
    message_text: str,
) -> None:
    """
    Behavior (for now):
        - Confirms we’re in the main nutrition side.
        - Shows the text it thinks the user sent (typed or transcribed).
    Later:
        - Will log meals, update targets, and show daily reports.
    """
    name = profile.get("Name") or "champ"
    await update.message.reply_text(
        f"🏋️ Main nutrition coach here, *{name}*.\n\n"
        "Here’s the message I’m working with:\n"
        f"“{message_text}”\n\n"
        "(Soon I’ll turn messages like this into logged meals, profile updates, or reports.)",
        parse_mode="Markdown",
    )


# --------------------- APP ENTRY POINT ---------------------


def main() -> None:
    """
    Behavior:
        - Checks for the bot token
        - Creates the Telegram application
        - Registers handlers (text, voice, photo)
        - Starts long polling (listening for messages)
    """
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from your .env file")

    # Build the bot application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # /start command
    application.add_handler(CommandHandler("start", start))

    # Text messages (not commands)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

    # Voice messages
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

    # Photo messages
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))

    print(
        "✅ Cal AI bot is running with text + voice (transcribed) + photo meal logging."
    )
    application.run_polling()


if __name__ == "__main__":
    main()
