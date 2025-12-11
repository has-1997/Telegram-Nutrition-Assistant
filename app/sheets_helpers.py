# sheets_helpers.py

import os
from typing import Tuple, Dict, Any, List, Optional

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


# ---------- PROFILE HELPERS ----------
def get_profile_by_user_id(user_id: int | str) -> Optional[Dict[str, Any]]:
    """
    Inputs:
        user_id: Telegram chat id (int or str).
    Returns:
        A dict with keys: User_ID, Name, Calories_target, Protein_target
        or None if not found.
    Purpose:
        Check if this user is already registered.
    """
    profile_ws, _ = get_profile_and_meals()
    records = profile_ws.get_all_records()  # list of dicts, skipping header row

    user_id_str = str(user_id)
    for row in records:
        if str(row.get("User_ID")) == user_id_str:
            return row

    return None


def create_profile(
    user_id: int | str,
    name: str,
    calories_target: float | int,
    protein_target: float | int,
) -> None:
    """
    Inputs:
        user_id: Telegram chat id.
        name: user's name.
        calories_target: daily calorie target.
        protein_target: daily protein target (grams).
    Returns:
        None (just writes to Google Sheets).
    Purpose:
        Append a brand new profile row.
    """
    profile_ws, _ = get_profile_and_meals()
    profile_ws.append_row(
        [
            str(user_id),
            name,
            float(calories_target),
            float(protein_target),
        ],
        value_input_option="USER_ENTERED",
    )


def update_profile_fields(
    user_id: int | str,
    fields: Dict[str, Any],
) -> None:
    """
    Inputs:
        user_id: Telegram chat id.
        fields: dict of column_name -> new_value
                e.g. {"Calories_target": 2300, "Protein_target": 160}
    Returns:
        None.
    Purpose:
        Update only the given fields for the matching user.
    """
    profile_ws, _ = get_profile_and_meals()
    records = profile_ws.get_all_records()
    headers = profile_ws.row_values(1)

    user_id_str = str(user_id)
    row_index = None

    # Find the row index (Google Sheets row number, including header)
    for idx, row in enumerate(records, start=2):  # data starts at row 2
        if str(row.get("User_ID")) == user_id_str:
            row_index = idx
            break

    if row_index is None:
        # No profile found, nothing to update
        return

    # For each field to update, find its column and write the new value
    for key, value in fields.items():
        if key in headers:
            col_index = headers.index(key) + 1  # Sheets columns are 1-based
            profile_ws.update_cell(row_index, col_index, value)


# ---------- MEALS HELPERS ----------
def append_meal_row(
    user_id: int | str,
    date_str: str,
    meal_description: str,
    calories: float | int,
    proteins: float | int,
    carbs: float | int,
    fats: float | int,
) -> None:
    """
    Inputs:
        user_id: Telegram chat id.
        date_str: date in 'YYYY-MM-DD' format.
        meal_description: text description of the meal.
        calories/proteins/carbs/fats: numeric macro values.
    Returns:
        None.
    Purpose:
        Append a new meal row for this user and date.
    """
    _, meals_ws = get_profile_and_meals()
    meals_ws.append_row(
        [
            str(user_id),
            date_str,
            meal_description,
            float(calories),
            float(proteins),
            float(carbs),
            float(fats),
        ],
        value_input_option="USER_ENTERED",
    )


def get_meals_for_date(user_id: int | str, date_str: str) -> List[Dict[str, Any]]:
    """
    Inputs:
        user_id: Telegram chat id.
        date_str: date in 'YYYY-MM-DD' format.
    Returns:
        List of dicts, each representing a meal row for that user on that date.
    Purpose:
        Fetch all meals for building daily reports.
    """
    _, meals_ws = get_profile_and_meals()
    records = meals_ws.get_all_records()
    user_id_str = str(user_id)

    results: List[Dict[str, Any]] = []
    for row in records:
        if str(row.get("User_ID")) == user_id_str and str(row.get("Date")) == date_str:
            results.append(row)

    return results


if __name__ == "__main__":
    # Small manual test: just print headers and counts.
    profile_ws, meals_ws = get_profile_and_meals()
    print("Profile headers:", profile_ws.row_values(1))
    print("Meals headers:", meals_ws.row_values(1))
    print("Profile rows (excluding header):", len(profile_ws.get_all_records()))
    print("Meals rows (excluding header):", len(meals_ws.get_all_records()))
