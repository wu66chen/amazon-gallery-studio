#!/usr/bin/env python3
"""Record plan-level approval (or a change request) with a bound plan hash."""

import argparse
from pathlib import Path

from ags_core import (AgsError, PLAN_FILE, append_approval, atomic_json, choose_representative,
                      load_task, plan_digest, read_json, resolve_product, save_task, task_dir)
from api_runtime import workspace


def recompute(plan):
    images = plan["images"]
    reused = sum(1 for t in images if t.get("render") == "reuse")
    retouch = sum(1 for t in images if t.get("render") == "retouch")
    generated = sum(1 for t in images if t.get("render") == "generate")
    plan["counts"] = {"total": len(images), "reused": reused, "retouch": retouch,
                      "generated": generated, "paid": retouch + generated}
    plan["white_background"]["counts"] = plan["counts"]
    plan["requirements"]["count"]["value"] = len(images)
    paid = [t for t in images if t.get("render") != "reuse"]
    representative = choose_representative(paid) if paid else None
    plan["representative_task_id"] = representative["id"] if representative else None
    plan["cost_quote"]["max_image_calls"] = plan["counts"]["paid"] + 5
    plan["plan_hash"] = plan_digest(plan)
    return plan


def apply_copy_choice(plan, choice, text):
    for task in plan["images"]:
        if task["usage"].startswith("Amazon MAIN"):
            task["copy"] = {"status": "not_applicable", "text": "", "candidates": []}
        elif choice == "none":
            task["copy"] = {"status": "none", "text": "", "candidates": []}
        elif choice == "provided":
            task["copy"] = {"status": "user_provided", "text": text or "", "candidates": []}
        elif choice == "suggest":
            task["copy"]["status"] = "suggested_pending"
    plan["requirements"]["copy_mode"] = {"value": choice, "source": "user_locked"}


def apply_white_choice(plan, choice):
    wb = plan["white_background"]
    main = next((t for t in plan["images"] if t["usage"].startswith("Amazon MAIN")), None)
    candidate = None
    if choice in ("reuse", "retouch"):
        verdicts = ("reuse",) if choice == "reuse" else ("retouch", "reuse")
        candidate = next((c for c in wb.get("candidates", []) if c.get("verdict") in verdicts), None)
        if not candidate:
            raise AgsError("没有符合该白底处理方式的候选，请重新规划或选择其他方式")
        if not main:
            raise AgsError("当前方案没有 MAIN 任务；请先用 plan_gallery.py --white-bg %s 重新生成方案" % choice)
        main["render"] = choice
        main["reuse_reference"] = candidate["reference_id"]
        wb["selected_reference_id"] = candidate["reference_id"]
    elif choice == "generate":
        if not main:
            raise AgsError("当前方案没有 MAIN 任务；请先用 plan_gallery.py --white-bg generate 重新生成方案")
        main["render"] = "generate"
        main["reuse_reference"] = None
        wb["selected_reference_id"] = None
    else:  # none
        if main:
            plan["images"] = [t for t in plan["images"] if t is not main]
            for number, task in enumerate(plan["images"], 1):
                task["display_number"] = number
                task["id"] = "img-%02d" % number
                task["usage"] = task["usage"].replace("Amazon MAIN 首图", "Listing 副图")
        wb["selected_reference_id"] = None
    wb["choice"] = choice
    wb["confirmed"] = True
    plan["requirements"]["white_background"] = {"value": choice, "source": "user_locked"}
    return recompute(plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--product")
    parser.add_argument("--user-expression", required=True, help="The operator's actual approval/change wording")
    parser.add_argument("--decision", choices=("approved", "change_requested"), default="approved")
    parser.add_argument("--authorized-image-calls", type=int,
                        help="Total paid image calls authorized for this gallery (0 allowed when all images are reused)")
    parser.add_argument("--total-cost-usd", type=float)
    parser.add_argument("--quote-status", choices=("verified", "estimated", "unavailable"), default="unavailable")
    parser.add_argument("--copy-choice", choices=("none", "provided", "suggest"))
    parser.add_argument("--copy-text")
    parser.add_argument("--white-choice", choices=("reuse", "retouch", "generate", "none"))
    parser.add_argument("--representative-task", type=int)
    args = parser.parse_args()
    try:
        root = workspace(args.workspace)
        product = resolve_product(root, args.product)
        directory = task_dir(root, product)
        plan = read_json(directory / PLAN_FILE)
        if not plan:
            raise AgsError("尚未生成套图方案")
        if args.decision == "change_requested":
            append_approval(root, product, stage="plan", decision="change_requested",
                            plan_version=plan["version"], plan_hash=plan["plan_hash"],
                            source="chat_explicit", user_expression=args.user_expression,
                            requested_change=args.user_expression)
            task = load_task(root, product)
            task["state"] = "planning"
            save_task(root, product, task)
            print("已记录修改要求，方案未被批准。")
            return
        if args.authorized_image_calls is None:
            raise AgsError("批准方案时必须给出 --authorized-image-calls（本次最多允许的付费生图调用数）")
        if args.quote_status == "unavailable" and args.total_cost_usd is not None:
            raise AgsError("无法可靠估价时不要填写金额，改用调用次数授权")
        if args.copy_choice:
            apply_copy_choice(plan, args.copy_choice, args.copy_text)
        if plan["requirements"]["copy_mode"]["value"] == "ask" and not args.copy_choice:
            raise AgsError("文案方式尚未确定：请让用户选择 1/2/不要文案，再传 --copy-choice")
        if args.white_choice:
            apply_white_choice(plan, args.white_choice)
        plan["white_background"]["confirmed"] = True
        if args.representative_task:
            chosen = next((t for t in plan["images"] if t["display_number"] == args.representative_task), None)
            if not chosen or chosen.get("render") == "reuse":
                raise AgsError("该编号不存在或为复用图片，不能作为需要付费生成的代表图")
            plan["representative_task_id"] = chosen["id"]
        paid = plan.get("counts", {}).get("paid", 0)
        if args.authorized_image_calls < 0:
            raise AgsError("授权调用数不能为负")
        if args.authorized_image_calls < 0 or (paid > 0 and args.authorized_image_calls == 0):
            raise AgsError("本套还有 %d 张需要付费生成/修整，授权调用数至少为 1" % paid)
        plan["cost_quote"].update({"status": args.quote_status, "amount_usd": args.total_cost_usd,
                                    "max_image_calls": args.authorized_image_calls})
        plan["plan_hash"] = plan_digest(plan)
        atomic_json(directory / PLAN_FILE, plan)
        append_approval(root, product, stage="plan", decision="approved",
                        plan_version=plan["version"], plan_hash=plan["plan_hash"],
                        authorized_image_calls=args.authorized_image_calls,
                        authorized_total_cost_usd=args.total_cost_usd,
                        cost_quote_status=args.quote_status,
                        white_background_choice=plan["white_background"]["choice"],
                        reused_images=plan["counts"]["reused"],
                        source="chat_explicit", user_expression=args.user_expression)
        task = load_task(root, product)
        task["plan_version"] = plan["version"]
        task["plan_hash"] = plan["plan_hash"]
        task["representative_task_id"] = plan["representative_task_id"]
        task["budget"].update({"authorized_image_calls": args.authorized_image_calls,
                               "authorized_total_cost_usd": args.total_cost_usd,
                               "quote_status": args.quote_status})
        task["state"] = "plan_approved"
        save_task(root, product, task)
        print("方案已批准：%s（版本 %d，hash %s…）" % (product, plan["version"], plan["plan_hash"][:12]))
        print("图片构成：共 %d 张｜复用 %d｜修整 %d｜新生成 %d｜需付费 %d"
              % (plan["counts"]["total"], plan["counts"]["reused"], plan["counts"]["retouch"],
                 plan["counts"]["generated"], plan["counts"]["paid"]))
        print("授权生图调用：%d 次；费用报价状态：%s" % (args.authorized_image_calls, args.quote_status))
        print("代表图：%s" % ("第 %02d 张" % next(t for t in plan["images"] if t["id"] == plan["representative_task_id"])["display_number"]
                            if plan.get("representative_task_id") else "无（全部为复用图片）"))
    except (AgsError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
