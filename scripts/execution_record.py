#!/usr/bin/env python3
"""Write a redacted, model-agnostic execution record for one gallery task."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", required=True, choices=("识别", "方案", "生图", "单张初筛", "整套初筛", "终审"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--status", required=True, choices=("未开始", "进行中", "通过", "失败", "待人工复核"))
    parser.add_argument("--calls", type=int, default=0)
    parser.add_argument("--tokens", type=int, default=0)
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    if args.calls < 0 or args.tokens < 0:
        parser.error("calls and tokens must be non-negative")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "record_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": args.stage,
        "model": args.model,
        "status": args.status,
        "calls": args.calls,
        "tokens": args.tokens,
        "note": args.note,
        "secret_redaction": "No API key or raw authorization header is stored.",
    }
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
