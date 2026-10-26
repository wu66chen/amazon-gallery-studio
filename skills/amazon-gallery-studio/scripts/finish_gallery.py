#!/usr/bin/env python3
"""Generate remaining image tasks (or reuse approved source images) with partial delivery."""

import argparse
import hashlib
import json
from pathlib import Path

from ags_core import (AgsError, BudgetError, PLAN_FILE, PROFILE_FILE, atomic_json, build_prompt,
                      contact_sheet, cost_summary, finish_request, product_dir,
                      read_json, require_plan_approval, require_representative_approval,
                      reserve_paid_call, resolve_product, save_task, set_state, task_dir, technical_check)
from api_runtime import endpoint, workspace
from providers import ProviderError, edit_image, vision_json
from generate_representative import QA_PROMPT, task_reference_paths

SET_PROMPT = """You are reviewing a complete Amazon image set. Return ONLY JSON:
{ "status": "pass|revise|uncertain|unavailable",
  "coverage": [strings], "consistency": [strings],
  "issues": [{"number": int, "item": str, "severity": "low|medium|high", "evidence": str}],
  "duplicates": [strings], "summary": str }
Check that all planned numbers are present, colours/SKUs are not mixed or missing, scenes do not repeat,
and the set shares one visual language. Reused white MAIN images should be judged on white background,
product fidelity and MAIN composition, not on scene aesthetics. Do not claim Amazon compliance."""


def candidate_dir(root, product):
    return product_dir(root, product, "03_最终套图") / "待审候选"


def label_for(task):
    return "".join(ch for ch in task["purpose"] if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")[:24] or "商品图"


def source_path(root, product, profile, task):
    ref_id = task.get("reuse_reference")
    ref = next((r for r in profile.get("references", []) if r["reference_id"] == ref_id), None)
    if not ref:
        return None
    return product_dir(root, product, "01_原始素材") / ref["file"]


def render_report(root, product, plan, records, whole, status):
    final_dir = product_dir(root, product, "03_最终套图")
    final_dir.mkdir(parents=True, exist_ok=True)
    summary = cost_summary(root, product)
    sources = {"reused": 0, "retouched": 0, "generated": 0}
    for row in records["images"]:
        sources[row.get("source", "generated")] = sources.get(row.get("source", "generated"), 0) + 1
    lines = ["# 整套审核 · 待终审", "",
             "- 产品：%s" % product,
             "- 状态：%s" % status,
             "- 已完成：%d / %d 张" % (records["completed"], len(plan["images"])),
             "- 来源：复用 %d｜修整 %d｜新生成 %d" % (sources["reused"], sources["retouched"], sources["generated"]),
             "- 生图调用：%d 次｜视觉调用：%d 次" % (summary["image_calls"], summary["vision_calls"]),
             "- 已知费用：%s" % ("$%s" % summary["known_usd"] if summary["known_usd"] is not None else "无法核算"),
             "- 结果未知的请求：%d" % summary["unknown"], ""]
    if whole:
        lines += ["## 整套视觉初审（%s）" % whole.get("status", "unavailable"), whole.get("summary", "")]
        for issue in whole.get("issues", [])[:6]:
            lines.append("- 第 %s 张：%s（%s）" % (issue.get("number"), issue.get("item"), issue.get("evidence", "")))
    else:
        lines += ["## 整套视觉初审", "未执行或不可用。"]
    lines += ["", "## 逐图状态"]
    for row in records["images"]:
        lines.append("- %02d %s：%s｜%s｜%s" % (row["number"], row["purpose"], row.get("source", "generated"),
                                               row["technical"], row["visual"]))
    lines += ["", "> 自动检查不等于 Amazon 审核通过；复用判断也不是平台合规结论。"]
    report = final_dir / "整套审核_待审.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def run(root, product, *, dry_run=False):
    if dry_run:
        plan, _ = require_plan_approval(root, product)
        tasks = [t for t in plan["images"] if t["id"] != plan.get("representative_task_id")]
        return {"status": "dry-run", "total": len(plan["images"]),
                "remaining": [t["display_number"] for t in tasks], "tasks": tasks,
                "counts": plan.get("counts", {}), "report": None}
    plan, plan_approval = require_plan_approval(root, product)
    representative = next((t for t in plan["images"] if t["id"] == plan.get("representative_task_id")), None)
    if representative:
        plan, _, _ = require_representative_approval(root, product)
    directory = task_dir(root, product)
    profile = read_json(directory / PROFILE_FILE) or plan.get("product", {})
    final_dir = product_dir(root, product, "03_最终套图")
    approved_file = final_dir / representative.get("final_file", "") if representative else None
    style_images = [approved_file] if approved_file and approved_file.is_file() else []
    tasks = [t for t in plan["images"] if not representative or t["id"] != representative["id"]]
    target_dir = candidate_dir(root, product)
    target_dir.mkdir(parents=True, exist_ok=True)
    records = {"images": [], "completed": 0}
    if representative:
        records["completed"] = 1
        records["images"].append({"number": representative["display_number"], "purpose": representative["purpose"],
                                  "technical": "technical_pass", "visual": "approved",
                                  "source": "retouched" if representative.get("render") == "retouch" else "generated"})
    stop = False
    blocked = False
    for task in tasks:
        candidate = target_dir / ("%02d_%s.png" % (task["display_number"], label_for(task)))
        qa_file = directory / ("质检_%02d.json" % task["display_number"])
        if candidate.is_file() and qa_file.is_file():
            qa = read_json(qa_file, {})
            technical_status = qa.get("technical", {}).get("status", "technical_pass")
            visual_status = qa.get("visual", {}).get("status", "uncertain")
            records["images"].append({"number": task["display_number"], "purpose": task["purpose"],
                                      "technical": technical_status, "visual": visual_status,
                                      "source": qa.get("source", "generated"), "reused": True,
                                      "candidate": str(candidate)})
            records["completed"] += 1
            if technical_status != "technical_pass" or visual_status in ("revise", "unavailable"):
                set_state(root, product, "partial", "第 %02d 张已有初筛问题" % task["display_number"])
                stop = True
            continue
        if stop:
            records["images"].append({"number": task["display_number"], "purpose": task["purpose"],
                                      "technical": "not_generated", "visual": "not_generated",
                                      "source": task.get("render", "generate")})
            continue
        if task.get("render") == "reuse":
            source = source_path(root, product, profile, task)
            if not source or not source.is_file():
                records["images"].append({"number": task["display_number"], "purpose": task["purpose"],
                                          "technical": "failed", "visual": "not_generated",
                                          "source": "reused", "error": "复用原文件不存在"})
                stop = True
                continue
            from PIL import Image
            with Image.open(source) as original_image:
                original_image.convert("RGB").save(candidate, format="PNG")
            technical = technical_check(candidate, task)
            qa = {"status": "source_reuse", "issues": [],
                  "summary": "原图复用；复用判断基于导入时的技术检查与视觉评估，需人工确认。"}
            atomic_json(qa_file, {"technical": technical, "visual": qa, "source": "reused",
                                  "source_file": source.name,
                                  "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
            records["images"].append({"number": task["display_number"], "purpose": task["purpose"],
                                      "technical": technical["status"], "visual": qa["status"],
                                      "source": "reused", "candidate": str(candidate), "origin": source.name})
            records["completed"] += 1
            if technical["status"] != "technical_pass":
                set_state(root, product, "partial", "复用图未通过技术检查")
                stop = True
            continue
        if not references_ready(root, product, task):
            records["images"].append({"number": task["display_number"], "purpose": task["purpose"],
                                      "technical": "failed", "visual": "not_generated",
                                      "source": task.get("render", "generate"), "error": "缺少参考图"})
            stop = True
            continue
        references, _ = task_reference_paths(root, product, task)
        try:
            request_id = reserve_paid_call(root, product, kind="image", stage="batch",
                                           image_task_id=task["id"],
                                           meta={"size": task["pixel_target"],
                                                 "references": [str(r) for r in references],
                                                 "style_reference": bool(style_images),
                                                 "render": task.get("render", "generate")})
        except BudgetError as exc:
            records["images"].append({"number": task["display_number"], "purpose": task["purpose"],
                                      "technical": "not_generated", "visual": "not_generated",
                                      "source": task.get("render", "generate"), "error": str(exc)})
            set_state(root, product, "partial", str(exc))
            stop = True
            break
        prompt = build_prompt(profile, task, use_copy=True, style_reference=bool(style_images))
        if task.get("render") == "retouch":
            prompt += "\nRetouch task: replace the background with pure white RGB 255,255,255, remove props/text/watermarks, keep the product shape, colour, material appearance and details unchanged. No added elements."
        try:
            data, usage = edit_image(endpoint("image", root), references + style_images, prompt,
                                     size=task["pixel_target"], quality="high")
        except ProviderError as exc:
            finish_request(root, product, request_id, "unknown", error=str(exc)[:300])
            records["images"].append({"number": task["display_number"], "purpose": task["purpose"],
                                      "technical": "failed", "visual": "not_generated",
                                      "source": task.get("render", "generate"), "error": str(exc)[:300]})
            set_state(root, product, "blocked", "第 %02d 张请求结果未知，未自动重试" % task["display_number"])
            blocked = True
            stop = True
            break
        candidate.write_bytes(data)
        finish_request(root, product, request_id, "succeeded", usage=usage)
        technical = technical_check(candidate, task)
        try:
            visual, qa_usage = vision_json(endpoint("vision", root), references + [candidate], QA_PROMPT)
        except ProviderError as exc:
            visual, qa_usage = {"status": "unavailable", "issues": [], "summary": str(exc)[:200]}, {}
        source = "retouched" if task.get("render") == "retouch" else "generated"
        atomic_json(qa_file, {"technical": technical, "visual": visual, "usage": qa_usage, "source": source})
        records["images"].append({"number": task["display_number"], "purpose": task["purpose"],
                                  "technical": technical["status"], "visual": visual.get("status"),
                                  "source": source, "candidate": str(candidate),
                                  "issues": visual.get("issues", [])[:3]})
        records["completed"] += 1
        if technical["status"] != "technical_pass" or visual.get("status") in ("revise", "unavailable"):
            set_state(root, product, "partial", "第 %02d 张未通过初筛" % task["display_number"])
            stop = True
    recorded = {row["number"] for row in records["images"]}
    for task in tasks:
        if task["display_number"] not in recorded:
            records["images"].append({"number": task["display_number"], "purpose": task["purpose"],
                                      "technical": "not_generated", "visual": "not_generated",
                                      "source": task.get("render", "generate")})
    for row in records["images"]:
        match = next((t for t in plan["images"] if t["display_number"] == row["number"]), None)
        if match:
            if row.get("source") == "reused":
                match["status"] = "reused"
            elif row["technical"] == "technical_pass":
                match["status"] = "generated"
            else:
                match["status"] = "qa_revise"
            if row["visual"] in ("pass", "approved"):
                match["status"] = "qa_pass" if row.get("source") != "reused" else "reused"
            elif row["visual"] in ("revise", "unavailable"):
                match["status"] = "qa_revise"
    atomic_json(directory / PLAN_FILE, plan)
    images_for_set = [target_dir / ("%02d_%s.png" % (t["display_number"], label_for(t))) for t in tasks]
    images_for_set = [p for p in images_for_set if p.is_file()]
    if approved_file and approved_file.is_file():
        images_for_set.append(approved_file)
    whole = None
    if images_for_set:
        try:
            selected_for_set = sorted(images_for_set)
            note = ""
            if len(selected_for_set) > 8:
                note = "仅将前 8 张送入整套初审（共 %d 张），其余逐图 QA 已单独保存。" % len(selected_for_set)
                selected_for_set = selected_for_set[:8]
            whole, _ = vision_json(endpoint("vision", root), selected_for_set,
                                   SET_PROMPT + "\nProduct facts: " + "；".join(profile.get("visible_facts", [])[:10]))
            if note:
                whole["summary"] = (whole.get("summary", "") + " " + note).strip()
                whole["truncated"] = True
        except ProviderError as exc:
            whole = {"status": "unavailable", "summary": str(exc)[:200], "issues": []}
    entries = []
    for task in plan["images"]:
        if task.get("final_file") and (final_dir / task["final_file"]).is_file():
            path = final_dir / task["final_file"]
        else:
            path = target_dir / ("%02d_%s.png" % (task["display_number"], label_for(task)))
        mark = "★" if representative and task["id"] == representative["id"] else (
            "⤺" if task.get("render") == "reuse" else "")
        entries.append((mark + "%02d" % task["display_number"], path))
    overview = final_dir / "套图总览_待审.jpg"
    contact_sheet(entries, overview)
    complete = records["completed"] == len(plan["images"])
    if blocked:
        status = "blocked"
    elif complete and not stop:
        status = "gallery_pending_approval"
    else:
        status = "partial"
    report = render_report(root, product, plan, records, whole, status)
    atomic_json(directory / "生成记录.json", {"records": records, "whole_set": whole, "status": status})
    set_state(root, product, status)
    return {"status": status, "completed": records["completed"], "remaining": len(plan["images"]) - records["completed"],
            "counts": plan.get("counts"), "overview": str(overview) if overview.exists() else None,
            "report": str(report)}


def references_ready(root, product, task):
    refs, _ = task_reference_paths(root, product, task)
    return bool(refs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--product")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        root = workspace(args.workspace)
        product = resolve_product(root, args.product)
        result = run(root, product, dry_run=args.dry_run)
    except (AgsError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
