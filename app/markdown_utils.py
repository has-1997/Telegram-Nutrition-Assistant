# markdown_utils.py

from typing import List
from telegram.helpers import escape_markdown


def escape_markdown_v2(text: str) -> str:
    """
    Inputs:
        text: any user-facing text (names, descriptions, Gemini replies, etc.).
    Returns:
        A version of the text safely escaped for Telegram MarkdownV2.
    Purpose:
        Prevents special characters from breaking formatting or causing errors.

    Usage pattern:
        - Use this on *dynamic* values (user names, descriptions, etc.).
        - Then insert those into your template strings that contain MarkdownV2.
    """
    if text is None:
        return ""
    return escape_markdown(str(text), version=2)


def chunk_for_telegram(text: str, max_len: int = 4000) -> List[str]:
    """
    Inputs:
        text: full message you want to send.
        max_len: maximum length per Telegram message (default 4000).
    Returns:
        A list of chunks, each at most max_len characters.
    Purpose:
        Split long messages into safe pieces while trying to cut on line boundaries.
    """
    if text is None:
        return []

    lines = text.splitlines(keepends=True)  # keep '\n'
    chunks: List[str] = []
    current = ""

    for line in lines:
        # If adding this line would exceed max_len, flush current
        if len(current) + len(line) > max_len:
            if current:
                chunks.append(current)
                current = ""

            # If the line itself is longer than max_len, hard-split it
            while len(line) > max_len:
                chunks.append(line[:max_len])
                line = line[max_len:]

        current += line

    if current:
        chunks.append(current)

    return chunks
