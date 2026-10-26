#!/usr/bin/env python3
"""Deprecated compatibility shim. Use import_assets.py for the vNext flow."""

import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", "--project", dest="workspace", type=Path)
    parser.add_argument("--set-name", required=True, help="Neutral product name (no vision naming)")
    parser.add_argument("--source", type=Path, action="append", default=[])
    args = parser.parse_args()
    command = [sys.executable, str(Path(__file__).with_name("import_assets.py")), "--offline",
               "--product", args.set_name]
    if args.workspace:
        command += ["--workspace", str(args.workspace)]
    for source in args.source:
        command += ["--source", str(source)]
    print("提示：task_assets.py 已弃用；本命令以离线模式调用 import_assets.py（不会自动识图）。")
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
