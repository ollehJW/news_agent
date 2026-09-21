"""Stable resource paths independent of module locations and process cwd."""
from pathlib import Path
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
