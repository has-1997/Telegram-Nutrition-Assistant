# gemini_helpers.py

import os
import json
from typing import Optional, Tuple, Dict, Any

from dotenv import load_dotenv
from google.genai import Client, types

# Load .env so we can read GEMINI_API_KEY
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Global client instance (initialized lazily)
_client: Optional[Client] = None


def _get_client() -> Client:
    """
    Inputs: none.
    Returns: Client instance configured with API key.
    Behavior:
        Creates and returns a singleton Client instance, using the API key.
    """
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is missing from .env")
        _client = Client(api_key=GEMINI_API_KEY)
    return _client


def ask_gemini_text(prompt: str, model_name: str = "gemini-2.5-flash") -> str:
    """
    Inputs:
        prompt: what you want to ask Gemini (plain text).
        model_name: which Gemini model to use.
    Returns:
        The text answer from Gemini (string). If empty, returns "".
    Purpose:
        Simple helper for text-only questions.
    """
    client = _get_client()
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
    )
    return response.text or ""


# ---------- TARGET ESTIMATION (TEXT-ONLY) ----------

def estimate_calorie_and_protein_targets(
    weight_kg: float,
    height_cm: float,
    age_years: int,
    goal: str,
) -> Tuple[float, float]:
    """
    Inputs:
        weight_kg: user's weight in kilograms.
        height_cm: user's height in centimeters.
        age_years: age in years.
        goal: text like 'gain muscle', 'lose fat', or 'maintain'.
    Returns:
        (calories_target, protein_target) as floats.
    Purpose:
        Ask Gemini to act like a nutrition coach and pick sensible daily targets.
        Uses structured output to ensure valid JSON response.
    """
    prompt = f"""You are an experienced sports nutrition coach.

A client has these stats:
- Weight: {weight_kg} kg
- Height: {height_cm} cm
- Age: {age_years} years
- Goal: {goal} (one of: gain muscle, lose fat, maintain)

Based on standard sports nutrition guidelines, choose sensible daily targets for calories and protein."""

    # Define the JSON schema for structured output
    response_schema = {
        "type": "object",
        "properties": {
            "calories_target": {
                "type": "integer",
                "description": "Daily calorie target in kcal"
            },
            "protein_target": {
                "type": "integer",
                "description": "Daily protein target in grams"
            }
        },
        "required": ["calories_target", "protein_target"]
    }

    client = _get_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=response_schema,
        ),
    )

    try:
        # Use the parsed response if available (structured output)
        if response.parsed and isinstance(response.parsed, dict):
            data = response.parsed
        else:
            # Fallback to parsing text if parsed is not available
            data = json.loads(response.text)
        
        calories = float(data["calories_target"])
        protein = float(data["protein_target"])
        return calories, protein
    except (KeyError, ValueError, json.JSONDecodeError, AttributeError):
        # Fallback if parsing fails: simple heuristic
        # Rough defaults: 30 kcal/kg and 1.8 g protein/kg
        calories = weight_kg * 30.0
        protein = weight_kg * 1.8
        return calories, protein


# ---------- VOICE → TEXT HELPER ----------

def transcribe_voice_message(
    audio_path: str,
    mime_type: str = "audio/ogg",
    model_name: str = "gemini-2.5-flash",
) -> str:
    """
    Inputs:
        audio_path: local path to the downloaded audio file.
        mime_type: MIME type for the audio (Telegram voice is usually audio/ogg).
        model_name: Gemini model to use.
    Returns:
        A short text message that represents what the user said,
        phrased as if they had typed it directly.
    Purpose:
        Turn a Telegram voice note into a normal text message for the bot.
    """
    client = _get_client()

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    prompt = """You are helping a nutrition coach bot on Telegram.

You will receive an audio message from a user talking about their food,
their day, or asking nutrition questions.

Task:
1. Understand what the user said.
2. Rewrite it as a single, clear text message as if the user had typed it.
3. Do NOT say "they said" or "user said" – just write the message content.
4. If they mention food they ate, keep those details.

Return plain text only, no bullet points, no JSON."""

    response = client.models.generate_content(
        model=model_name,
        contents=[
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
        ],
    )

    return response.text or ""


# ---------- MEAL PHOTO → MACROS HELPER ----------

def analyze_meal_image(
    image_path: str,
    mime_type: str = "image/jpeg",
    model_name: str = "gemini-2.5-flash",
) -> Dict[str, Any]:
    """
    Inputs:
        image_path: local path to the downloaded meal photo.
        mime_type: MIME type for the image (Telegram photos are usually JPEG).
        model_name: Gemini model to use.
    Returns:
        A dict with keys:
            - meal_description (str)
            - calories (float)
            - proteins (float)
            - carbs (float)
            - fats (float)
    Purpose:
        Look at a plate of food and estimate macros in a structured way.
        Uses structured output to ensure valid JSON response.
    """
    client = _get_client()

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    prompt = """You are a nutrition vision assistant.

You will see a photo of a meal. Your job:
1. Identify the main components of the meal (foods).
2. Estimate reasonable portion sizes.
3. Use typical macro values per 100 g to estimate:
   - total calories
   - grams of protein
   - grams of carbs
   - grams of fats

Provide a short description of the meal and the macro estimates."""

    # Define the JSON schema for structured output
    response_schema = {
        "type": "object",
        "properties": {
            "meal_description": {
                "type": "string",
                "description": "Short human-readable description of the meal (max 2 sentences)"
            },
            "calories": {
                "type": "integer",
                "description": "Estimated total calories"
            },
            "proteins": {
                "type": "integer",
                "description": "Estimated grams of protein"
            },
            "carbs": {
                "type": "integer",
                "description": "Estimated grams of carbohydrates"
            },
            "fats": {
                "type": "integer",
                "description": "Estimated grams of fats"
            }
        },
        "required": ["meal_description", "calories", "proteins", "carbs", "fats"]
    }

    response = client.models.generate_content(
        model=model_name,
        contents=[
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=response_schema,
        ),
    )

    try:
        # Use the parsed response if available (structured output)
        if response.parsed and isinstance(response.parsed, dict):
            data = response.parsed
        else:
            # Fallback to parsing text if parsed is not available
            data = json.loads(response.text)

        meal_description = str(data.get("meal_description", "")).strip()
        calories = float(data.get("calories", 0))
        proteins = float(data.get("proteins", 0))
        carbs = float(data.get("carbs", 0))
        fats = float(data.get("fats", 0))
    except (KeyError, ValueError, json.JSONDecodeError, AttributeError):
        # Fallback if parsing fails
        meal_description = "Meal (details could not be parsed)."
        calories = proteins = carbs = fats = 0.0

    return {
        "meal_description": meal_description,
        "calories": calories,
        "proteins": proteins,
        "carbs": carbs,
        "fats": fats,
    }


def plan_nutrition_action(message_text: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inputs:
        message_text: what the user said (typed or transcribed).
        profile: dict from Google Sheets with keys like Name, Calories_target, Protein_target.
    Returns:
        A dict describing what to do. Example shapes:

        {
          "action": "append_meal",
          "meal": {
            "description": "Chicken with rice and vegetables",
            "calories": 620,
            "proteins": 45,
            "carbs": 70,
            "fats": 15
          },
          "reply": "Logged your chicken and rice meal, nice job!"
        }

        {
          "action": "update_profile",
          "profile_updates": {
            "Calories_target": 2300,
            "Protein_target": 170
          },
          "reply": "Updated your daily targets to 2300 kcal and 170 g protein."
        }

        {
          "action": "get_report",
          "report_date": "2025-01-01",
          "reply": "Here is your report for 2025-01-01:"
        }

        {
          "action": "chat",
          "reply": "Short coaching-style answer..."
        }

    Purpose:
        Let Gemini act as the 'brain' that decides how to interpret a user's message.
        Uses structured output to ensure valid JSON response.
    """
    client = _get_client()

    name = str(profile.get("Name", "champ"))
    calories_target = profile.get("Calories_target", None)
    protein_target = profile.get("Protein_target", None)

    profile_summary = f"Name: {name}."
    if calories_target is not None and protein_target is not None:
        profile_summary += (
            f" Daily targets: {calories_target} kcal and {protein_target} g protein."
        )

    prompt = f"""You are Cal AI, a friendly but efficient nutrition coach bot.

User profile:
{profile_summary}

You will receive ONE message from the user. It might:
- Describe a meal they just ate (with or without macros).
- Ask to update their calorie/protein targets.
- Ask for a daily report (e.g. "show me today's report" or "report for 2025-01-01").
- Ask a general nutrition question.

Your job:
1. Decide ONE main action: "append_meal", "update_profile", "get_report", or "chat".
2. If action == "append_meal":
   - Build a meal object with:
     - description (short)
     - calories, proteins, carbs, fats (numbers, rough estimates if needed).
3. If action == "update_profile":
   - Build profile_updates with keys like "Calories_target" and "Protein_target"
     if the user clearly asked to change them.
4. If action == "get_report":
   - Choose report_date:
     - If they mention a specific date, use 'YYYY-MM-DD' format.
     - If they say things like "today" or "tonight", use "today".
     - If unclear, use "today".
5. Always include a short, friendly coaching reply in "reply".

Rules:
- Use ONLY one action per response.
- If something is not needed, you can omit that field or set it to null.
- Numbers must NOT be in quotes.

User message: {message_text}"""

    # Define the JSON schema for structured output
    response_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["append_meal", "update_profile", "get_report", "chat"],
                "description": "The main action to take"
            },
            "meal": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Short description of the meal"
                    },
                    "calories": {
                        "type": "integer",
                        "description": "Estimated calories"
                    },
                    "proteins": {
                        "type": "integer",
                        "description": "Estimated grams of protein"
                    },
                    "carbs": {
                        "type": "integer",
                        "description": "Estimated grams of carbohydrates"
                    },
                    "fats": {
                        "type": "integer",
                        "description": "Estimated grams of fats"
                    }
                },
                "required": ["description", "calories", "proteins", "carbs", "fats"]
            },
            "profile_updates": {
                "type": "object",
                "properties": {
                    "Calories_target": {
                        "type": "integer",
                        "description": "New daily calorie target"
                    },
                    "Protein_target": {
                        "type": "integer",
                        "description": "New daily protein target in grams"
                    }
                }
            },
            "report_date": {
                "type": "string",
                "description": "Date for the report in 'YYYY-MM-DD' format or 'today'"
            },
            "reply": {
                "type": "string",
                "description": "Short, friendly coaching reply message for the user"
            }
        },
        "required": ["action", "reply"]
    }

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=response_schema,
        ),
    )

    try:
        # Use the parsed response if available (structured output)
        if response.parsed and isinstance(response.parsed, dict):
            data = response.parsed
        else:
            # Fallback to parsing text if parsed is not available
            data = json.loads(response.text)
        
        if not isinstance(data, dict):
            raise ValueError("Parsed JSON is not an object")
        
        # Ensure at least action + reply exist
        action = data.get("action") or "chat"
        reply = data.get("reply") or "Got it!"
        data["action"] = action
        data["reply"] = reply
        return data
    except (KeyError, ValueError, json.JSONDecodeError, AttributeError):
        # Fallback: just treat it as a chat message
        return {
            "action": "chat",
            "reply": "I understand! Let me help you with that.",
        }


if __name__ == "__main__":
    # Optional manual tests (each will use an API call if you uncomment them).

    # 1) Simple greeting
    # print(ask_gemini_text("Say hi in one short sentence."))

    # 2) Example targets
    # cals, protein = estimate_calorie_and_protein_targets(
    #     weight_kg=75,
    #     height_cm=180,
    #     age_years=28,
    #     goal="gain muscle",
    # )
    # print("Estimated calories:", cals)
    # print("Estimated protein:", protein)

    # For voice and image tests, you would pass real file paths from your downloads/ folder.
    pass
