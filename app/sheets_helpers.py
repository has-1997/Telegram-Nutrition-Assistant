# sheets_helpers.py

import os
from typing import Tuple

from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Load .env so we can read GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON_PATH
load_dotenv()

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDS_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH", "credentials.json")

# Scopes = what kind of access we want (read/write Sheets + Drive)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_gspread_client() -> gspread.Client:
    """
    Inputs: none (reads from env + credentials.json).
    Returns: an authorized gspread Client object.
    Purpose: log in as our service account so we can use Google Sheets.
    """
    if not GOOGLE_SHEET_ID:
        raise RuntimeError("GOOGLE_SHEET_ID is missing from .env")

    if not os.path.exists(CREDS_PATH):
        raise RuntimeError(f"Service account file not found at: {CREDS_PATH}")

    credentials = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    client = gspread.authorize(credentials)
    return client


def get_profile_and_meals() -> Tuple[gspread.Worksheet, gspread.Worksheet]:
    """
    Inputs: none.
    Returns: (profile_sheet, meals_sheet)
    Purpose: open our main Google Sheet and return the two tabs we care about.
    """
    client = get_gspread_client()
    sheet = client.open_by_key(GOOGLE_SHEET_ID)

    profile_ws = sheet.worksheet("Profile")
    meals_ws = sheet.worksheet("Meals")
    return profile_ws, meals_ws

if __name__ == "__main__":
    # Small manual test: try to connect and print the header rows.
    profile, meals = get_profile_and_meals()
    print("Profile headers:", profile.row_values(1))
    print("Meals headers:", meals.row_values(1))
