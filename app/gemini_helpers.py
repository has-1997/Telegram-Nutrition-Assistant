# gemini_helpers.py

import os
from typing import Optional

from dotenv import load_dotenv
from google.genai import Client

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

if __name__ == "__main__":
    # Tiny manual test; this will cost a small API call.
    print(ask_gemini_text("Say hi in one short sentence."))
