#!/usr/bin/env python3
"""Create and organize the operator-facing task asset folders."""

import argparse
import hashlib
import shutil
from pathlib import Path


FOLDERS = (
    "01_原始素材",
    "02_代表图审批",
    "03_最终套图",
    "04_记录与报告",
)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def import_images(project, set_name, sources, *, move=False):
    """Import explicit files or direct children of directories; preserve existing user work."""
    root = project.expanduser().resolve() / "任务资产与审批"
    dest_dir = root / "01_原始素材" / set_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    imported = []
    for source in sources:
        source = source.expanduser().resolve(strict=True)
        paths = sorted(source.iterdir()) if source.is_dir() else [source]
        for item in paths:
            if not item.is_file() or item.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if item.parent == dest_dir:
                imported.append(item)
                continue
            target = dest_dir / item.name
            if target.exists():
                digest = hashlib.sha256(item.read_bytes()).hexdigest()[:8]
                if item.read_bytes() == target.read_bytes():
                    imported.append(target)
                    continue
                target = dest_dir / (item.stem + "_" + digest + item.suffix)
                if target.exists() and target.read_bytes() != item.read_bytes():
                    raise ValueError("name collision: " + str(target))
            if not target.exists():
                if move:
                    shutil.move(str(item), str(target))
                else:
                    shutil.copy2(item, target)
            imported.append(target)
    if not imported:
        raise ValueError("no supported image files at the supplied path")
    return imported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="Project root; defaults to the script's project, never to the source folder")
    parser.add_argument("--set-name", required=True, help="Chinese set name, e.g. 3D打印圣诞树")
    parser.add_argument("--source", type=Path, action="append", default=[], help="External source file to copy; repeatable")
    parser.add_argument("--move", action="store_true", help="Move external originals only when the operator explicitly requests it")
    parser.add_argument("--copy-to", type=Path, action="append", default=[], help="Agent-created file to copy into the set's final folder; repeatable")
    args = parser.parse_args()
    if not args.set_name.strip() or "/" in args.set_name or "\\" in args.set_name:
        parser.error("set-name must be one folder name")
    project = Path(__file__).resolve().parents[1]
    if args.project:
        project = args.project.expanduser().resolve()
        if not (project / ".gallery-project-root").is_file():
            parser.error("--project must point to a gallery workspace with .gallery-project-root; do not pass the external image directory")
    root = project / "任务资产与审批"
    for folder in FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "01_原始素材" / args.set_name).mkdir(exist_ok=True)
    (root / "02_代表图审批" / args.set_name).mkdir(exist_ok=True)
    final_dir = root / "03_最终套图" / args.set_name
    final_dir.mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# 任务资产与审批\n\n"
            "本目录是当前项目的唯一任务资产与审批目录。\n\n"
            "- `01_原始素材/<套图名称>/`：用户素材；用户已放入的文件尽量不动\n"
            "- `02_代表图审批/<套图名称>/`：代表图和审批材料\n"
            "- `03_最终套图/<套图名称>/`：最终图片、总览和最终审核报告\n"
            "- `04_记录与报告/`：识别、方案、费用和质量记录\n",
            encoding="utf-8",
        )
    imported = import_images(project, args.set_name, args.source, move=args.move) if args.source else []
    for source in args.copy_to:
        source = source.expanduser().resolve(strict=True)
        destination = final_dir / source.name
        shutil.copy2(source, destination)
    print("任务资产：%s" % root)
    print("导入图片：%d 张" % len(imported))


if __name__ == "__main__":
    main()
