#!/usr/bin/env python3
"""Run VisionService against one sample label image (live OpenAI call).

Usage:
  uv run python scripts/extract_sample.py
  uv run python scripts/extract_sample.py path/to/label.jpg
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE = ROOT / "samples" / "sample_label.jpg"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str]) -> int:
    load_dotenv(ROOT / ".env")

    image_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_SAMPLE
    if not image_path.is_file():
        print(f"Sample image not found: {image_path}", file=sys.stderr)
        return 1

    # Import after dotenv so OPENAI_API_KEY is available.
    from app.vision import VisionService

    image_bytes = image_path.read_bytes()
    try:
        label = VisionService().extract(image_bytes)
    except RuntimeError as exc:
        print(f"Exit check FAILED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(label.model_dump(), indent=2))

    populated = any(value is not None for value in label.model_dump().values())
    if not populated:
        print(
            "Exit check FAILED: ExtractedLabel has no populated fields.",
            file=sys.stderr,
        )
        return 2

    print("Exit check OK: ExtractedLabel is populated.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
