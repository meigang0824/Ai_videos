from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = BASE_DIR / "backend"
STORAGE_DIR = BACKEND_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
TMP_DIR = STORAGE_DIR / "tmp"
OUTPUT_DIR = BASE_DIR / "outputs"
VOICE_DIR = BASE_DIR / "voices"

DEFAULT_BACKGROUND_VIDEO = os.getenv("DEFAULT_BACKGROUND_VIDEO", "").strip()

try:
    MAX_UPLOAD_BYTES = max(1, int(os.getenv("MAX_UPLOAD_BYTES", str(1024 * 1024 * 1024))))
except ValueError:
    MAX_UPLOAD_BYTES = 1024 * 1024 * 1024

# Kept only for compatibility with moviepy_service. API-only builds must not load
# local Whisper; subtitle timing falls back to text estimation unless an API flow
# supplies timing data.
WHISPER_MODEL_DIR = ""

for path in (STORAGE_DIR, UPLOAD_DIR, TMP_DIR, OUTPUT_DIR, VOICE_DIR):
    path.mkdir(parents=True, exist_ok=True)
