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
    get_meals_for_date,
    update_profile_fields,
)
from gemini_helpers import (
    estimate_calorie_and_protein_targets,
    transcribe_voice_message,
    analyze_meal_image,
    plan_nutrition_action,
)
from media_helpers import (
    download_voice_file,
    download_photo_file,
)
from markdown_utils import (
    escape_markdown_v2,
    chunk_for_telegram,
)

# -------------------------------------------------
# Logging & config
# -------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def today_str() -> str:
    """Return today's date as 'YYYY-MM-DD' (UTC)."""
    return datetime.utcnow().strftime("%Y-%m-%d")


async def send_markdown(update: Update, text: str) -> None:
    """
    Inputs:
        update: Telegram update (we use update.message.reply_text).
        text: full Markdown-formatted message.
    Behavior:
        Splits the text into chunks ≤ 4000 chars and sends each one.
    """
    for chunk in chunk_for_telegram(text, max_len=4000):
        await update.message.reply_text(chunk, parse_mode="Markdown")


# -------------------------------------------------
# Daily report helper
# -------------------------------------------------


def build_daily_report_message(chat_id: int | str, date_str: str) -> str:
    """
    Inputs:
        chat_id: Telegram chat ID.
        date_str: 'YYYY-MM-DD'.
    Returns:
        A human-friendly summary of that day's meals vs targets.
    """
    profile = get_profile_by_user_id(chat_id)
    if profile is None:
        return (
            "I couldn’t find your profile for this report 🤔\n"
            "Try sending /start again so I can set you up."
        )

    meals = get_meals_for_date(chat_id, date_str)
    name_raw = profile.get("Name") or "champ"
    name = escape_markdown_v2(name_raw)
    date_safe = escape_markdown_v2(date_str)

    if not meals:
        return (
            f"📅 Daily report for *{date_safe}* – *{name}*\n\n"
            "You haven’t logged any meals for this day yet.\n"
            "Send me photos or descriptions of what you eat and I’ll track everything for you 💪"
        )

    total_calories = 0.0
    total_proteins = 0.0
    total_carbs = 0.0
    total_fats = 0.0

    lines = []
    for row in meals:
        desc_raw = str(row.get("Meal_description", "Meal")).strip()
        desc = escape_markdown_v2(desc_raw)
        try:
            cals = float(row.get("Calories", 0) or 0)
            prot = float(row.get("Proteins", 0) or 0)
            carbs = float(row.get("Carbs", 0) or 0)
            fats = float(row.get("Fats", 0) or 0)
        except (TypeError, ValueError):
            cals = prot = carbs = fats = 0.0

        total_calories += cals
        total_proteins += prot
        total_carbs += carbs
        total_fats += fats

        lines.append(
            f"• {desc} — {int(cals)} kcal, {int(prot)} g P, {int(carbs)} g C, {int(fats)} g F"
        )

    try:
        target_cal = float(profile.get("Calories_target") or 0)
    except (TypeError, ValueError):
        target_cal = 0.0

    try:
        target_prot = float(profile.get("Protein_target") or 0)
    except (TypeError, ValueError):
        target_prot = 0.0

    def progress_bar(total: float, target: float) -> str:
        if target <= 0:
            return "No target set."
        ratio = max(0.0, min(total / target, 2.0))  # cap at 200%
        pct = int(round(ratio * 100))
        bar_len = 20
        filled = int(round(min(bar_len, max(0, ratio * bar_len))))
        bar = "█" * filled + "░" * (bar_len - filled)
        return f"{bar} {pct}%"

    calories_line = "🔥 Calories: "
    if target_cal > 0:
        calories_line += f"{int(total_calories)}/{int(target_cal)} kcal\n"
        calories_line += progress_bar(total_calories, target_cal)
    else:
        calories_line += f"{int(total_calories)} kcal (no target set)"

    protein_line = "🍗 Protein: "
    if target_prot > 0:
        protein_line += f"{int(total_proteins)}/{int(target_prot)} g\n"
        protein_line += progress_bar(total_proteins, target_prot)
    else:
        protein_line += f"{int(total_proteins)} g (no target set)"

    header = f"📅 Daily report for *{date_safe}* – *{name}*\n"
    meals_block = "\n".join(lines)

    msg = (
        f"{header}\n"
        "Logged meals:\n"
        f"{meals_block}\n\n"
        f"{calories_line}\n\n"
        f"{protein_line}\n\n"
        f"Carbs: {int(total_carbs)} g\n"
        f"Fats: {int(total_fats)} g\n\n"
        "Keep going, legend 💪"
    )
    return msg


# -------------------------------------------------
# /start handler
# -------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /start from chat_id=%s", chat_id)

    profile = get_profile_by_user_id(chat_id)

    if profile is None:
        # New user → registration
        context.user_data.clear()
        context.user_data["mode"] = "registration"
        context.user_data["registration_step"] = "ask_name"
        context.user_data["registration_data"] = {}

        text = (
            "🔥 Welcome to *Cal AI* – your nutrition assistant!\n\n"
            "Looks like this is your first time here.\n"
            "Let’s set up your profile so I can coach you properly.\n\n"
            "First question: what’s your *first name*, champ? 💪"
        )
        await send_markdown(update, text)
    else:
        # Existing user
        name_raw = profile.get("Name") or "champ"
        name = escape_markdown_v2(name_raw)
        context.user_data.clear()
        context.user_data["mode"] = "main"

        text = (
            f"Welcome back, *{name}* 💪\n\n"
            "You’re already registered.\n"
            "Send me meal descriptions, photos, or voice messages, "
            "or ask for a daily report."
        )
        await send_markdown(update, text)


# -------------------------------------------------
# Text routing
# -------------------------------------------------


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.message is None:
        return

    chat_id = update.effective_chat.id
    user_text = (update.message.text or "").strip()
    logger.info("Received TEXT from chat_id=%s: %s", chat_id, user_text)

    profile = get_profile_by_user_id(chat_id)

    if profile is None:
        context.user_data.setdefault("mode", "registration")
        await registration_assistant(update, context)
    else:
        context.user_data["mode"] = "main"
        await main_nutrition_agent(update, context, profile, user_text)


# -------------------------------------------------
# Voice routing (with Gemini)
# -------------------------------------------------


async def handle_voice_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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

    local_path = await download_voice_file(update, context)
    if local_path is None:
        await update.message.reply_text(
            "It was not possible to process the file. "
            "File type not supported or download failed 😕",
        )
        return

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

    logger.info(
        "Transcribed VOICE from chat_id=%s into TEXT: %s",
        chat_id,
        transcribed_text,
    )
    context.user_data["mode"] = "main"
    await main_nutrition_agent(update, context, profile, transcribed_text)


# -------------------------------------------------
# Photo routing (image → macros + log meal)
# -------------------------------------------------


async def handle_photo_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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

    local_path = await download_photo_file(update, context)
    if local_path is None:
        await update.message.reply_text(
            "It was not possible to process the file. "
            "File type not supported or download failed 😕",
        )
        return

    try:
        analysis = analyze_meal_image(
            image_path=local_path,
            mime_type="image/jpeg",
        )
    except Exception as e:
        logger.exception("Error while analyzing meal image: %s", e)
        await update.message.reply_text(
            "Something went wrong while analyzing that meal photo 😔\n"
            "Please try again, or describe the meal in text.",
        )
        return

    meal_description_raw = analysis.get("meal_description", "Meal")
    meal_description = escape_markdown_v2(meal_description_raw)
    calories = float(analysis.get("calories", 0) or 0)
    proteins = float(analysis.get("proteins", 0) or 0)
    carbs = float(analysis.get("carbs", 0) or 0)
    fats = float(analysis.get("fats", 0) or 0)

    date_str = today_str()
    logger.info(
        "Logging meal from photo for chat_id=%s on %s: %s (kcal=%.1f, P=%.1f, C=%.1f, F=%.1f)",
        chat_id,
        date_str,
        meal_description_raw,
        calories,
        proteins,
        carbs,
        fats,
    )

    try:
        append_meal_row(
            user_id=chat_id,
            date_str=date_str,
            meal_description=meal_description_raw,
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
    await send_markdown(update, reply_text)


# -------------------------------------------------
# Registration assistant
# -------------------------------------------------


async def registration_assistant(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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

        name = escape_markdown_v2(data["name"])
        text = (
            f"Nice to meet you, {name} 😎\n\n"
            "Do you already know your daily *calorie* and *protein* targets?\n"
            "Reply with **yes** or **no**."
        )
        await send_markdown(update, text)
        return

    # Step 2: Ask if they know their targets
    if step == "ask_know_targets":
        text_lower = user_text.lower()
        if text_lower in {"yes", "y", "yeah", "yep", "sure"}:
            data["knows_targets"] = True
            context.user_data["registration_step"] = "ask_calories_target"

            text = (
                "Awesome 🔥\n\n"
                "Please send your *daily calorie target* as a **number only**.\n"
                "Example: `2200`"
            )
            await send_markdown(update, text)
            return
        elif text_lower in {"no", "n", "nope", "nah"}:
            data["knows_targets"] = False
            context.user_data["registration_step"] = "ask_weight"

            text = (
                "No problem at all 💪\n\n"
                "I’ll help you *calculate* good targets based on your stats.\n\n"
                "First, what’s your *weight in kg*?\n"
                "Example: `75`"
            )
            await send_markdown(update, text)
            return
        else:
            text = "Please reply with **yes** or **no** so I know whether you already have targets 😊"
            await send_markdown(update, text)
            return

    # ----- PATH A: USER KNOWS TARGETS -----

    if step == "ask_calories_target":
        try:
            calories = float(user_text)
        except ValueError:
            text = "I need a *number only* for calories, champ 🔢\n" "Example: `2200`"
            await send_markdown(update, text)
            return

        data["calories_target"] = calories
        context.user_data["registration_step"] = "ask_protein_target"

        text = (
            "Got it 🔥\n\n"
            "Now send your *daily protein target* in grams as a **number only**.\n"
            "Example: `150`"
        )
        await send_markdown(update, text)
        return

    if step == "ask_protein_target":
        try:
            protein = float(user_text)
        except ValueError:
            text = "I need a *number only* for protein, in grams 🔢\n" "Example: `150`"
            await send_markdown(update, text)
            return

        data["protein_target"] = protein

        name_raw = data.get("name", "champ")
        name = escape_markdown_v2(name_raw)
        calories_target = data["calories_target"]
        protein_target = data["protein_target"]

        logger.info(
            "Creating profile (manual targets) for chat_id=%s name=%s calories=%s protein=%s",
            chat_id,
            name_raw,
            calories_target,
            protein_target,
        )

        create_profile(
            user_id=chat_id,
            name=name_raw,
            calories_target=calories_target,
            protein_target=protein_target,
        )

        context.user_data.clear()
        context.user_data["mode"] = "main"

        text = (
            "Awesome, champ 💪\n\n"
            f"Your nutrition targets are locked in:\n"
            f"🔥 *{int(calories_target)}* kcal\n"
            f"🍗 *{int(protein_target)}* g protein\n\n"
            "From now on you can:\n"
            "• Send me meal descriptions or photos to log your food 🥗\n"
            "• Ask for a *daily report* to see your progress 📊\n"
            "• Update your targets any time.\n\n"
            "Whenever you're ready, tell me about your next meal!"
        )
        await send_markdown(update, text)
        return

    # ----- PATH B: USER DOES NOT KNOW TARGETS (USE GEMINI) -----

    if step == "ask_weight":
        try:
            weight = float(user_text)
        except ValueError:
            text = "I need a *number only* for your weight in kg 🔢\n" "Example: `75`"
            await send_markdown(update, text)
            return

        data["weight_kg"] = weight
        context.user_data["registration_step"] = "ask_height"

        text = "Nice ⚖️\n\n" "What’s your *height in cm*?\n" "Example: `180`"
        await send_markdown(update, text)
        return

    if step == "ask_height":
        try:
            height = float(user_text)
        except ValueError:
            text = "I need a *number only* for your height in cm 🔢\n" "Example: `180`"
            await send_markdown(update, text)
            return

        data["height_cm"] = height
        context.user_data["registration_step"] = "ask_age"

        text = "Got it 📏\n\n" "How old are you (in *years*)?\n" "Example: `28`"
        await send_markdown(update, text)
        return

    if step == "ask_age":
        try:
            age = int(user_text)
        except ValueError:
            text = "I need a *whole number* for your age in years 🔢\n" "Example: `28`"
            await send_markdown(update, text)
            return

        data["age_years"] = age
        context.user_data["registration_step"] = "ask_goal"

        text = (
            "Perfect 🎯\n\n"
            "Finally, what’s your main goal?\n"
            "You can say things like:\n"
            "• gain muscle\n"
            "• lose fat\n"
            "• maintain\n"
        )
        await send_markdown(update, text)
        return

    if step == "ask_goal":
        goal_text = user_text.lower()
        data["goal_raw"] = goal_text

        if "gain" in goal_text or "bulk" in goal_text or "muscle" in goal_text:
            goal_norm = "gain muscle"
        elif "lose" in goal_text or "cut" in goal_text or "fat" in goal_text:
            goal_norm = "lose fat"
        else:
            goal_norm = "maintain"

        weight = float(data["weight_kg"])
        height = float(data["height_cm"])
        age = int(data["age_years"])

        text = (
            "Love that goal 🙌\n\n"
            "Give me a second while I calculate smart daily targets for you… 🤖"
        )
        await send_markdown(update, text)

        calories_target, protein_target = estimate_calorie_and_protein_targets(
            weight_kg=weight,
            height_cm=height,
            age_years=age,
            goal=goal_norm,
        )

        name_raw = data.get("name", "champ")

        logger.info(
            "Creating profile (Gemini targets) for chat_id=%s name=%s "
            "weight=%.2f height=%.2f age=%d goal=%s calories=%.2f protein=%.2f",
            chat_id,
            name_raw,
            weight,
            height,
            age,
            goal_norm,
            calories_target,
            protein_target,
        )

        create_profile(
            user_id=chat_id,
            name=name_raw,
            calories_target=calories_target,
            protein_target=protein_target,
        )

        context.user_data.clear()
        context.user_data["mode"] = "main"

        text = (
            "Targets calculated and locked in, legend 💪\n\n"
            f"Here’s what I recommend based on your stats and goal:\n"
            f"🔥 *{int(calories_target)}* kcal per day\n"
            f"🍗 *{int(protein_target)}* g protein per day\n\n"
            "From now on you can:\n"
            "• Send me meal descriptions or photos to log your food 🥗\n"
            "• Ask for a *daily report* to see your progress 📊\n"
            "• Update your targets any time as things change.\n\n"
            "Whenever you're ready, tell me about your next meal!"
        )
        await send_markdown(update, text)
        return


# -------------------------------------------------
# Main nutrition agent using Gemini planner
# -------------------------------------------------


async def main_nutrition_agent(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    profile: dict,
    message_text: str,
) -> None:
    """
    Behavior:
        - Ask Gemini what to do with the message (append_meal, update_profile, get_report, chat).
        - Call the right helper functions.
        - Reply to the user with a friendly message.
    """
    chat_id = update.effective_chat.id
    plan = plan_nutrition_action(message_text, profile)

    action = plan.get("action", "chat")
    reply_raw = plan.get("reply", "") or ""

    # Escape the AI reply so any special characters don't break Markdown
    reply = escape_markdown_v2(reply_raw)

    # --- Append meal from text ---
    if action == "append_meal":
        meal = plan.get("meal") or {}
        desc_raw = meal.get("description") or "Meal"
        desc = escape_markdown_v2(desc_raw)
        try:
            calories = float(meal.get("calories", 0) or 0)
            proteins = float(meal.get("proteins", 0) or 0)
            carbs = float(meal.get("carbs", 0) or 0)
            fats = float(meal.get("fats", 0) or 0)
        except (TypeError, ValueError):
            calories = proteins = carbs = fats = 0.0

        date_str = today_str()

        logger.info(
            "Logging meal (text) for chat_id=%s on %s: %s (kcal=%.1f, P=%.1f, C=%.1f, F=%.1f)",
            chat_id,
            date_str,
            desc_raw,
            calories,
            proteins,
            carbs,
            fats,
        )

        append_meal_row(
            user_id=chat_id,
            date_str=date_str,
            meal_description=desc_raw,
            calories=calories,
            proteins=proteins,
            carbs=carbs,
            fats=fats,
        )

        if not reply.strip():
            reply = escape_markdown_v2("Nice, I’ve logged that meal for you 💪")

        reply += (
            f"\n\nLogged: {desc}\n"
            f"🔥 ~{int(calories)} kcal, "
            f"🍗 ~{int(proteins)} g P, "
            f"🍞 ~{int(carbs)} g C, "
            f"🥑 ~{int(fats)} g F"
        )
        await send_markdown(update, reply)
        return

    # --- Update profile targets ---
    if action == "update_profile":
        raw_updates = plan.get("profile_updates") or {}
        normalized_updates: Dict[str, Any] = {}

        for key, value in raw_updates.items():
            if key is None:
                continue
            k = str(key).lower()
            if k in {"calories_target", "calories", "kcal"}:
                try:
                    normalized_updates["Calories_target"] = float(value)
                except (TypeError, ValueError):
                    pass
            elif k in {"protein_target", "proteins", "protein"}:
                try:
                    normalized_updates["Protein_target"] = float(value)
                except (TypeError, ValueError):
                    pass

        if normalized_updates:
            update_profile_fields(chat_id, normalized_updates)
            logger.info(
                "Updated profile for chat_id=%s with %s",
                chat_id,
                normalized_updates,
            )
            if not reply.strip():
                parts = []
                if "Calories_target" in normalized_updates:
                    parts.append(f"{int(normalized_updates['Calories_target'])} kcal")
                if "Protein_target" in normalized_updates:
                    parts.append(
                        f"{int(normalized_updates['Protein_target'])} g protein"
                    )
                joined = ", ".join(parts)
                reply = escape_markdown_v2(f"Updated your daily targets to {joined} 💪")
            await send_markdown(update, reply)
        else:
            text = (
                "I wasn’t fully sure how to update your targets from that message 🤔\n"
                "Try saying something like: “Set my calories to 2300 and protein to 170g.”"
            )
            await send_markdown(update, text)
        return

    # --- Daily report ---
    if action == "get_report":
        date_token = plan.get("report_date", "today")
        if isinstance(date_token, str):
            token_lower = date_token.lower().strip()
            if token_lower in {"today", "tonight", "now"}:
                date_str = today_str()
            else:
                date_str = date_token.strip()
        else:
            date_str = today_str()

        report_message = build_daily_report_message(chat_id, date_str)
        await send_markdown(update, report_message)
        return

    # --- Chat / default ---
    if not reply.strip():
        reply = escape_markdown_v2(
            "Got it! If you tell me what you ate, I can log it, "
            "or you can ask me for a daily report 📊"
        )
    await send_markdown(update, reply)


# -------------------------------------------------
# App entry point
# -------------------------------------------------


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from your .env file")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))

    print(
        "✅ Cal AI bot is running with Gemini-powered actions + daily reports + Markdown helpers."
    )
    application.run_polling()


if __name__ == "__main__":
    main()
