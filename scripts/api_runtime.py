"""Shared, project-bound Tokease credentials and API client configuration."""

import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
BASE_URL = "https://tokease.com/v1"
VISION_MODEL = "gemini-3.5-flash"
IMAGE_MODEL = "gpt-image-2"


def credentials():
    key = os.getenv("TOKEASE_API_KEY", "").strip()
    if not key:
        file = PROJECT / ".env"
        if file.exists():
            for line in file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("TOKEASE_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("\"'")
                    break
    if not key:
        raise ValueError("项目根目录 .env 缺少 TOKEASE_API_KEY；请配置后重试")
    return {"key": key, "base_url": BASE_URL, "vision_model": VISION_MODEL, "image_model": IMAGE_MODEL}
