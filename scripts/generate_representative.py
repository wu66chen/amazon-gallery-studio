#!/usr/bin/env python3
"""Generate one representative image using the Tokease GPT Image 2 edit API."""

import argparse
import base64
from pathlib import Path
import json

from api_runtime import IMAGE_MODEL, PROJECT, credentials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-name", required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True, help="Previously approved plan JSON in this project's records folder")
    parser.add_argument("--image", action="append", type=Path, required=True)
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", default="high")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = PROJECT / "任务资产与审批"
    records = (root / "04_记录与报告").resolve()
    plan_file = args.plan.expanduser().resolve(strict=True)
    if records not in plan_file.parents:
        parser.error("方案文件必须来自当前项目的 04_记录与报告")
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    if plan.get("confirmed") is not True:
        parser.error("套图方案还未获得用户确认，不得调用付费生图")
    source_dir = (root / "01_原始素材" / args.set_name).resolve()
    if not source_dir.is_dir():
        parser.error("未找到本套原始素材目录")
    images = [p.expanduser().resolve(strict=True) for p in args.image]
    if any(source_dir not in p.parents for p in images):
        parser.error("先把项目外素材导入本项目 01_原始素材，再调用生图")
    out = (args.output or root / "02_代表图审批" / args.set_name / "01_代表图.png").resolve()
    if (root / "02_代表图审批" / args.set_name).resolve() not in out.parents:
        parser.error("代表图只能保存到当前项目的代表图审批目录")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        parser.error("代表图已存在；请指定新的文件名，避免覆盖审批中的图片")
    try:
        from openai import OpenAI
    except ImportError:
        parser.error("缺少 openai Python SDK；请运行 python3 -m pip install -r requirements.txt")
    cfg = credentials()
    client = OpenAI(api_key=cfg["key"], base_url=cfg["base_url"])
    files = [image.open("rb") for image in images]
    try:
        response = client.images.edit(model=IMAGE_MODEL, image=files, prompt=args.prompt_file.resolve(strict=True).read_text(encoding="utf-8"),
                                      size=args.size, quality=args.quality, output_format="png")
    finally:
        for source in files:
            source.close()
    if not response.data or not response.data[0].b64_json:
        parser.error("图像接口未返回图片；请查看账户用量，不要假定本次生成成功")
    out.write_bytes(base64.b64decode(response.data[0].b64_json))
    print("代表图：%s" % out)


if __name__ == "__main__":
    main()
