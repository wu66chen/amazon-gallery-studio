#!/usr/bin/env python3
"""Approve a representative version, promote it, and optionally continue the batch."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from ags_core import (AgsError, PLAN_FILE, append_approval, atomic_json, authorized_calls, load_task,
                      product_dir, read_json, require_plan_approval, resolve_product, save_task, task_dir)
from api_runtime import workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--product")
    parser.add_argument("--image", type=Path, help="Exact representative version the user approved")
    parser.add_argument("--user-expression", required=True)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--decline", action="store_true")
    parser.add_argument("--authorized-image-calls", type=int,
                        help="Additional image calls authorized at this approval (not a new total)")
    parser.add_argument("--execute", action="store_true", help="Continue the remaining images in the same run")
    args = parser.parse_args()
    if args.approve == args.decline:
        parser.error("choose exactly one of --approve or --decline")
    try:
        root = workspace(args.workspace)
        product = resolve_product(root, args.product)
        directory = task_dir(root, product)
        plan, _ = require_plan_approval(root, product)
        selected = next((t for t in plan["images"] if t["id"] == plan.get("representative_task_id")), None)
        if not selected:
            if args.decline:
                raise AgsError("本套没有代表图任务，无法拒绝代表图")
            if not args.execute:
                raise AgsError("本套全部为原图复用，没有代表图需要批准；请直接运行 finish_gallery.py 生成总览与报告")
            from finish_gallery import run
            result = run(root, product)
            print(json.dumps({"status": result["status"], "completed": result["completed"],
                              "remaining": result["remaining"], "report": result["report"]},
                             ensure_ascii=False, indent=2))
            return
        if args.decline:
            append_approval(root, product, stage="representative", decision="change_requested",
                            plan_version=plan["version"], plan_hash=plan["plan_hash"],
                            representative_image_id=selected["id"], source="chat_explicit",
                            user_expression=args.user_expression)
            task = load_task(root, product)
            task["state"] = "representative_pending_approval"
            save_task(root, product, task)
            print("已记录修改要求；代表图未批准，未生成其余图片。")
            return
        if not args.image:
            parser.error("--approve requires --image pointing to the approved version")
        image = args.image.expanduser().resolve(strict=True)
        review_dir = product_dir(root, product, "02_代表图审批").resolve()
        if review_dir not in image.parents:
            raise AgsError("代表图必须来自当前产品的 02_代表图审批 目录")
        if not image.name.startswith("%02d_" % selected["display_number"]):
            raise AgsError("批准文件与方案中的代表图编号不一致")
        data = image.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        final_dir = product_dir(root, product, "03_最终套图")
        final_dir.mkdir(parents=True, exist_ok=True)
        label = "".join(ch for ch in selected["purpose"] if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")[:24] or "商品图"
        target = final_dir / ("%02d_%s.png" % (selected["display_number"], label))
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise AgsError("最终目录已有不同的同编号图片，请先人工核对，不自动覆盖")
        else:
            shutil.copy2(image, target)
        selected["status"] = "approved"
        selected["approved_version_file"] = image.name
        selected["approved_sha256"] = digest
        selected["final_file"] = target.name
        atomic_json(directory / PLAN_FILE, plan)
        append_approval(root, product, stage="representative", decision="approved",
                        plan_version=plan["version"], plan_hash=plan["plan_hash"],
                        representative_image_id=selected["id"],
                        representative_file=image.name, representative_sha256=digest,
                        authorized_image_calls=0, source="chat_explicit", user_expression=args.user_expression)
        task = load_task(root, product)
        if args.authorized_image_calls:
            if args.authorized_image_calls < 0:
                raise AgsError("追加授权次数不能为负")
            append_approval(root, product, stage="extra_cost", decision="approved",
                            plan_version=plan["version"], plan_hash=plan["plan_hash"],
                            authorized_image_calls=args.authorized_image_calls,
                            source="chat_explicit", user_expression=args.user_expression)
            task["budget"]["authorized_image_calls"] = authorized_calls(root, product)
        task["state"] = "representative_approved"
        save_task(root, product, task)
        print("代表图已批准并归档：%s" % target)
        print("已授权生图调用：%d 次" % authorized_calls(root, product))
        if args.execute:
            from finish_gallery import run
            result = run(root, product)
            print(json.dumps({"status": result["status"], "completed": result["completed"],
                              "remaining": result["remaining"], "report": result["report"]},
                             ensure_ascii=False, indent=2))
        else:
            print("下一步：生成剩余图片（同一次批准可以直接继续，无需用户再次确认）。")
    except (AgsError, ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
