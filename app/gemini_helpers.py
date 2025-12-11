# gemini_helpers.py

import os
import json
import logging
from typing import Optional, Tuple

from dotenv import load_dotenv
from google.genai import Client
from google.genai import types

logger = logging.getLogger(__name__)

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

    # response.text is a convenient shortcut to the main text
    return response.text or ""


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
        Ask Gemini to act like a nutrition coach and pick daily targets.
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
    except (KeyError, ValueError, json.JSONDecodeError, AttributeError) as e:
        # Fallback if parsing fails: simple heuristic
        # Rough defaults: 30 kcal/kg and 1.8 g protein/kg
        logger.warning(f"Failed to parse structured response: {e}. Using fallback values.")
        calories = weight_kg * 30.0
        protein = weight_kg * 1.8
        return calories, protein


if __name__ == "__main__":
    # Tiny manual test; this will use an API call.
    cals, protein = estimate_calorie_and_protein_targets(
        weight_kg=90,
        height_cm=173,
        age_years=28,
        goal="gain muscle",
    )
    print("Estimated calories:", cals)
    print("Estimated protein:", protein)
