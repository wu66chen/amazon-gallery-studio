#!/usr/bin/env python3
"""Record the final human decision for a gallery and promote accepted candidates."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from ags_core import (AgsError, PLAN_FILE, append_approval, atomic_json, load_task, now, product_dir, read_json,
                      resolve_product, save_task, set_state, task_dir)
from api_runtime import workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--product")
    parser.add_argument("--user-expression", required=True,
                        help='The operator\'s exact wording, e.g. "通过" or "开始下一套"')
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--request-change", action="store_true")
    parser.add_argument("--number", type=int, action="append", default=[],
                        help="Image number(s) the user wants changed")
    parser.add_argument("--accept-partial", action="store_true",
                        help="User explicitly accepts a partial gallery after seeing the issues")
    args = parser.parse_args()
    if args.approve == args.request_change:
        parser.error("choose exactly one of --approve or --request-change")
    try:
        root = workspace(args.workspace)
        product = resolve_product(root, args.product)
        directory = task_dir(root, product)
        plan = read_json(directory / PLAN_FILE)
        if not plan:
            raise AgsError("找不到套图方案")
        final_dir = product_dir(root, product, "03_最终套图")
        candidate_dir = final_dir / "待审候选"
        if args.request_change:
            append_approval(root, product, stage="gallery", decision="change_requested",
                            plan_version=plan["version"], plan_hash=plan["plan_hash"],
                            image_numbers=args.number, source="chat_explicit",
                            user_expression=args.user_expression)
            task = load_task(root, product)
            task["state"] = "gallery_pending_approval"
            save_task(root, product, task)
            print("已记录修改要求：%s" % ("、".join(str(n) for n in args.number) or "未指定编号"))
            return
        missing = []
        promoted = []
        for task in plan["images"]:
            label = "".join(ch for ch in task["purpose"] if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")[:24] or "商品图"
            source = candidate_dir / ("%02d_%s.png" % (task["display_number"], label))
            target = final_dir / ("%02d_%s.png" % (task["display_number"], label))
            if target.is_file():
                promoted.append(target.name)
                continue
            if task.get("final_file") and (final_dir / task["final_file"]).is_file():
                promoted.append(task["final_file"])
                continue
            if not source.is_file():
                missing.append(task["display_number"])
                continue
            shutil.copy2(source, target)
            task["final_file"] = target.name
            promoted.append(target.name)
        if missing and not args.accept_partial:
            raise AgsError("还有编号未完成：%s。如用户已知情并明确接受部分交付，加 --accept-partial。" %
                           "、".join("%02d" % n for n in missing))
        atomic_json(directory / PLAN_FILE, plan)
        overview = final_dir / "套图总览_待审.jpg"
        if overview.is_file() and not (final_dir / "套图总览.jpg").is_file():
            shutil.copy2(overview, final_dir / "套图总览.jpg")
        report = final_dir / "整套审核_待审.md"
        final_report = final_dir / "最终审核报告.md"
        if report.is_file():
            text = report.read_text(encoding="utf-8").replace("待终审", "用户已通过（可能含已知问题）")
            text += "\n- 用户原文：%s\n- 缺失编号：%s\n" % (args.user_expression,
                                                          "、".join(str(n) for n in missing) or "无")
            final_report.write_text(text, encoding="utf-8")
        append_approval(root, product, stage="gallery", decision="approved",
                        plan_version=plan["version"], plan_hash=plan["plan_hash"],
                        image_numbers=[t["display_number"] for t in plan["images"]],
                        missing_numbers=missing, partial=bool(missing),
                        source="chat_explicit", user_expression=args.user_expression)
        task = load_task(root, product)
        task["state"] = "gallery_approved"
        task["final_approved_at"] = now()
        save_task(root, product, task)
        print("已记录用户通过：%s" % product)
        print("最终文件：%d 张；缺失：%s" % (len(promoted), "、".join(str(n) for n in missing) or "无"))
    except (AgsError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
