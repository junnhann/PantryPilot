"""Central settings, read once from environment variables / .env.

Keeping everything here means no other file calls os.getenv directly,
and the API key is never hardcoded anywhere.
"""
import os

from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root (if present)


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
DEMO_MODE: bool = _bool("DEMO_MODE", True)
STORE_MODE: str = os.getenv("STORE_MODE", "mock")
HEADLESS: bool = _bool("HEADLESS", True)
MAX_PARALLEL: int = int(os.getenv("MAX_PARALLEL", "4"))
HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", "8000"))
SCREENSHOT_FPS: float = float(os.getenv("SCREENSHOT_FPS", "2"))
