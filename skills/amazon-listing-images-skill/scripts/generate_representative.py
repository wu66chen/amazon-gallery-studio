#!/usr/bin/env python3
"""Generate one representative image for the approved plan, with versions and QA."""

import argparse
import json
from pathlib import Path

from ags_core import (AgsError, PLAN_FILE, PROFILE_FILE, atomic_json, build_prompt, contact_sheet,
                      finish_request, load_task, now, probe_image, product_dir, read_json, representative_scores,
                      require_plan_approval, reserve_paid_call, resolve_product, save_task, set_state,
                      task_dir, technical_check, versioned_path)
from api_runtime import endpoint, workspace
from providers import ProviderError, edit_image, parse_json_answer, vision_json

QA_PROMPT = """Compare the candidate image with the original product references.
Return ONLY JSON:
{ "status": "pass|revise|uncertain|unavailable",
  "strengths": [strings],
  "issues": [{"item": str, "severity": "low|medium|high", "location": str, "evidence": str}],
  "uncertain": [strings],
  "copy_check": {"text_expected": str, "text_visible": str, "status": "pass|fail|not_applicable"},
  "summary": str }
Judge product shape, proportions, colours, visible logo/print, closures, texture, hands and image quality.
Do not invent defects when the match is good. Never claim Amazon compliance."""


def task_reference_paths(root, product, task):
    profile = read_json(task_dir(root, product) / PROFILE_FILE) or {}
    by_id = {ref["reference_id"]: ref for ref in profile.get("references", [])}
    base = product_dir(root, product, "01_原始素材")
    paths = []
    for ref_id in task.get("references", []):
        ref = by_id.get(ref_id)
        if ref and (base / ref["file"]).is_file():
            paths.append(base / ref["file"])
    if not paths:
        paths = [base / ref["file"] for ref in profile.get("references", []) if (base / ref["file"]).is_file()]
    return paths, profile


def run_qa(root, product, cfg, references, candidate, task):
    try:
        data, usage = vision_json(cfg, references + [candidate], QA_PROMPT)
        if data.get("status") not in ("pass", "revise", "uncertain", "unavailable"):
            data["status"] = "uncertain"
        return data, usage
    except ProviderError as exc:
        return {"status": "unavailable", "strengths": [], "issues": [],
                "uncertain": ["视觉初审不可用：%s" % str(exc)[:200]], "summary": "无法读取图片进行初审。"}, {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--product")
    parser.add_argument("--task", type=int, help="Representative display number; default from approved plan")
    parser.add_argument("--size", help="Override pixel target")
    parser.add_argument("--quality", default="high")
    args = parser.parse_args()
    try:
        root = workspace(args.workspace)
        product = resolve_product(root, args.product)
        plan, _ = require_plan_approval(root, product)
        paid_tasks = [t for t in plan["images"] if t.get("render") != "reuse"]
        if not paid_tasks:
            raise AgsError("本套全部为原图复用，没有需要生成的代表图；请直接运行 finish_gallery.py")
        if args.task:
            selected = next((t for t in plan["images"] if t["display_number"] == args.task), None)
            if not selected:
                raise AgsError("代表图编号不存在")
        else:
            selected = next((t for t in paid_tasks if t["id"] == plan.get("representative_task_id")), None)
            if not selected:
                selected = representative_scores(paid_tasks)[0][2]
        references, profile = task_reference_paths(root, product, selected)
        if (profile.get("vision") or {}).get("status") != "complete":
            raise AgsError("原图视觉识别未完成（%s），不能进入高保真商品生图。请先修复识图。" % (profile.get("vision") or {}).get("status"))
        if not references:
            raise AgsError("当前编号没有可用的原始参考图")
        prompt = build_prompt(profile, selected, use_copy=True)
        directory = task_dir(root, product)
        review_dir = product_dir(root, product, "02_代表图审批")
        reviews = [p for p in review_dir.glob("%02d_*_v*.png" % selected["display_number"])]
        version = len(reviews) + 1
        label = "".join(ch for ch in selected["purpose"] if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")[:24] or "代表图"
        output = versioned_path(review_dir, selected["display_number"], label, version)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise AgsError("代表图版本文件已存在，拒绝覆盖：%s" % output.name)
        request_id = reserve_paid_call(root, product, kind="image", stage="representative",
                                       image_task_id=selected["id"],
                                       meta={"version": version, "size": args.size or selected["pixel_target"]})
        cfg = endpoint("image", root)
        try:
            data, usage = edit_image(cfg, references, prompt, size=args.size or selected["pixel_target"],
                                     quality=args.quality)
        except ProviderError as exc:
            finish_request(root, product, request_id, "unknown", error=str(exc)[:300])
            set_state(root, product, "blocked", "代表图请求结果未知，未自动重试：" + str(exc)[:200])
            raise AgsError("代表图未能确认生成：%s\n已暂停以避免重复扣费。" % exc)
        output.write_bytes(data)
        finish_request(root, product, request_id, "succeeded", usage=usage)
        info = probe_image(output)
        technical = technical_check(output, selected)
        qa, qa_usage = run_qa(root, product, endpoint("vision", root), references, output, selected)
        atomic_json(directory / ("代表图QA_v%02d.json" % version), {"technical": technical, "visual": qa,
                                                                   "usage": qa_usage, "created_at": now()})
        plan_task = next(t for t in plan["images"] if t["id"] == selected["id"])
        plan_task.setdefault("versions", []).append({"version": version, "file": output.name,
                                                      "sha256": __import__("hashlib").sha256(output.read_bytes()).hexdigest(),
                                                      "status": "pending_approval"})
        plan["representative_task_id"] = selected["id"]
        atomic_json(directory / PLAN_FILE, plan)
        task = load_task(root, product)
        task["representative_task_id"] = selected["id"]
        task["state"] = "representative_reviewed"
        save_task(root, product, task)
        (directory / ("代表图审核_v%02d.md" % version)).write_text(
            "# 代表图审核 v%02d\n\n- 编号：%02d\n- 用途：%s\n- 文件：%s\n- 实际尺寸：%dx%d\n"
            "- 技术检查：%s%s\n- 视觉初审：%s\n- 摘要：%s\n"
            % (version, selected["display_number"], selected["purpose"], output.name,
               info["width"], info["height"], technical["status"],
               ("（%s）" % "；".join(technical["issues"])) if technical["issues"] else "",
               qa.get("status"), qa.get("summary", "")), encoding="utf-8")
        print("代表图：%02d｜%s｜v%02d" % (selected["display_number"], selected["purpose"], version))
        print("文件：%s" % output)
        print("实际尺寸：%dx%d｜技术检查：%s｜视觉初审：%s" % (info["width"], info["height"], technical["status"], qa.get("status")))
        if qa.get("issues"):
            print("需注意：" + "；".join("%s（%s）" % (i.get("item"), i.get("location", "")) for i in qa["issues"][:3]))
        print("\n这是整套图的一张样张，用来验证产品保真与视觉方向。")
        print("1. 通过，按已授权范围生成剩余图片")
        print("2. 修改这张（说明要改的地方）")
    except (AgsError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
