#!/usr/bin/env python3
"""Import product photos, identify the product, then create the four product folders."""

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from ags_core import (AgsError, REQUESTS_FILE, SUPPORTED, atomic_json, combine_white_verdict, convert_working_copy,
                      ensure_product, now, probe_image, product_dir, safe_name, sha256_file, split_batches,
                      start_task, task_dir, unique_product_name, white_metrics, PROFILE_FILE, save_task)
from api_runtime import endpoint, initialise
from providers import ProviderError, vision_json

VISION_PROMPT = """Inspect every supplied product photo. Return ONLY a JSON object:
product_name (short Chinese product name using only high-confidence visible facts),
product_group (string), confidence (high|medium|low),
visible_facts (array), inferences (array of {claim, confidence}), unknowns (array),
variants (array of {label, colour, evidence, reference_index}),
structural_features (array), white_background_candidates (array of 1-based reference indices),
white_background_assessments (array of {reference_index, verdict: reuse|retouch|unusable|uncertain,
reasons, has_props, has_text, product_complete, variant_label, composition_note}).
Assess each obvious white-background reference for MAIN use: background, props, text/watermark,
product completeness, composition and whether it matches the selling product. Be conservative;
when unsure use uncertain and explain.
Do not infer dimensions, certifications, materials or performance as facts. Never use the
source folder name as the product name. reference_index is the 1-based index within this batch.
Use Chinese for descriptive text."""


def gather(sources):
    files = []
    for source in sources:
        source = source.expanduser().resolve(strict=True)
        candidates = sorted(source.iterdir()) if source.is_dir() else [source]
        for item in candidates:
            if item.is_file() and item.suffix.lower() in SUPPORTED:
                files.append(item)
    if not files:
        raise AgsError("指定路径中没有支持的图片（JPG/PNG/WEBP/TIFF）")
    seen, unique = set(), []
    for path in files:
        digest = sha256_file(path)
        if digest not in seen:
            seen.add(digest)
            unique.append(path)
    return unique


def prepare_working_copy(source, staging):
    """Return a readable working file and a conversion note."""
    try:
        probe_image(source)
        if source.suffix.lower() in (".jpg", ".jpeg", ".png"):
            return source, None
        converted = staging / (source.stem + "_converted.png")
        convert_working_copy(source, converted)
        return converted, "converted"
    except AgsError:
        try:
            converted = staging / (source.stem + "_converted.png")
            convert_working_copy(source, converted)
            return converted, "converted"
        except Exception as exc:
            raise AgsError("无法读取或转换图片 %s：%s" % (source.name, exc))


def analyze(files, workspace, analysis_json=None):
    if analysis_json:
        saved = json.loads(Path(analysis_json).read_text(encoding="utf-8"))
        data = saved.get("analysis") or saved
        return data, {"model": saved.get("model", "provided"), "calls": 0, "usage": saved.get("usage", {}),
                      "status": "complete"}
    cfg = endpoint("vision", workspace)
    merged = {"product_name": None, "product_group": "", "confidence": "low", "visible_facts": [],
              "inferences": [], "unknowns": [], "variants": [], "structural_features": [],
              "white_background_candidates": [], "white_background_assessments": []}
    calls, usage_total = 0, {}
    batches = split_batches(files, 6)
    for offset, batch in enumerate(batches):
        data, usage = vision_json(cfg, batch, VISION_PROMPT)
        calls += 1
        for key in ("visible_facts", "inferences", "unknowns", "structural_features"):
            merged[key].extend(data.get(key, []) or [])
        for variant in data.get("variants", []) or []:
            if isinstance(variant, dict) and isinstance(variant.get("reference_index"), int):
                variant["reference_index"] += offset * 6
            merged["variants"].append(variant)
        for item in data.get("white_background_candidates", []) or []:
            index = item.get("reference_index") if isinstance(item, dict) else item
            if isinstance(index, int):
                merged["white_background_candidates"].append(index + offset * 6)
        for assessment in data.get("white_background_assessments", []) or []:
            if isinstance(assessment, dict) and isinstance(assessment.get("reference_index"), int):
                item = dict(assessment)
                item["reference_index"] += offset * 6
                merged["white_background_assessments"].append(item)
        if not merged["product_name"]:
            merged["product_name"] = data.get("product_name")
            merged["product_group"] = data.get("product_group", "")
            merged["confidence"] = data.get("confidence", "low")
        usage_total["total_tokens"] = usage_total.get("total_tokens", 0) + int(usage.get("total_tokens", 0) or 0)
    if not merged["product_name"]:
        raise AgsError("视觉模型没有返回可用的产品名称")
    return merged, {"model": cfg["model"], "calls": calls, "usage": usage_total, "status": "complete"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--product", help="Fallback product name when vision is skipped")
    parser.add_argument("--offline", action="store_true", help="Do not call a vision model")
    parser.add_argument("--analysis-json", type=Path, help="Reuse a saved vision analysis (no paid call)")
    args = parser.parse_args()
    try:
        root = initialise(args.workspace)
        files = gather(args.source)
    except (AgsError, OSError) as exc:
        parser.error(str(exc))
    staging = Path(tempfile.mkdtemp(prefix=".ags-import-", dir=root))
    try:
        prepared, notes = [], []
        for source in files:
            working, note = prepare_working_copy(source, staging)
            prepared.append({"source": source, "working": working, "sha256": sha256_file(source),
                             "original_name": source.name, "conversion": note})
            if note:
                notes.append("%s：%s" % (source.name, note))
        if args.offline:
            if not args.product:
                parser.error("离线导入需要 --product 提供中性产品名")
            analysis = {"product_name": args.product, "product_group": "", "confidence": "low",
                        "visible_facts": [], "inferences": [], "unknowns": ["未执行视觉识别，外观未核实"],
                        "variants": [], "structural_features": [], "white_background_candidates": [],
                        "white_background_assessments": []}
            vision_meta = {"model": None, "calls": 0, "usage": {}, "status": "unavailable"}
        else:
            try:
                analysis, vision_meta = analyze([item["working"] for item in prepared], root, args.analysis_json)
            except (AgsError, ProviderError) as exc:
                parser.error("视觉识别失败：%s\n可修复后重试，或使用 --product 与 --offline 生成待核实的中性任务。" % exc)
        base = safe_name(args.product or analysis.get("product_name"))
        product = unique_product_name(root, base)
        ensure_product(root, product)
        references = []
        for index, item in enumerate(prepared, 1):
            target = product_dir(root, product, "01_原始素材") / ("R%02d_%s" % (index, item["original_name"]))
            if not target.exists():
                shutil.copy2(item["source"], target)
            info = probe_image(target)
            references.append({"reference_id": "R%02d" % index, "original_name": item["original_name"],
                               "file": target.name, "sha256": item["sha256"],
                               "width": info["width"], "height": info["height"], "format": info["format"],
                               "conversion": item["conversion"]})
        assessments = []
        seen = set()
        for item in analysis.get("white_background_assessments", []) or []:
            index = item.get("reference_index")
            if not isinstance(index, int) or not 1 <= index <= len(references):
                continue
            seen.add(index)
            path = product_dir(root, product, "01_原始素材") / references[index - 1]["file"]
            metrics = white_metrics(path)
            combined = combine_white_verdict(item, metrics)
            assessments.append({"reference_id": references[index - 1]["reference_id"],
                                "reference_index": index,
                                "variant_label": item.get("variant_label", ""),
                                "vision_verdict": combined["vision_verdict"],
                                "verdict": combined["verdict"],
                                "reasons": combined["reasons"],
                                "technical": metrics,
                                "composition_note": item.get("composition_note", "")})
        for index in analysis.get("white_background_candidates", []) or []:
            index = int(index)
            if index in seen or not 1 <= index <= len(references):
                continue
            path = product_dir(root, product, "01_原始素材") / references[index - 1]["file"]
            metrics = white_metrics(path)
            combined = combine_white_verdict({}, metrics)
            assessments.append({"reference_id": references[index - 1]["reference_id"],
                                "reference_index": index, "variant_label": "",
                                "vision_verdict": "uncertain", "verdict": combined["verdict"],
                                "reasons": combined["reasons"], "technical": metrics,
                                "composition_note": "视觉模型未提供逐项白底评估"})
        verdicts = {item["verdict"] for item in assessments}
        white_status = ("reusable" if "reuse" in verdicts else "retouch" if "retouch" in verdicts
                        else "unusable" if "unusable" in verdicts else "uncertain" if assessments else "none")
        profile = {"product_name": product, "product_group": analysis.get("product_group", ""),
                   "confidence": analysis.get("confidence", "low"),
                   "visible_facts": analysis.get("visible_facts", []),
                   "inferences": analysis.get("inferences", []),
                   "unknowns": analysis.get("unknowns", []),
                   "variants": analysis.get("variants", []),
                   "structural_features": analysis.get("structural_features", []),
                   "white_background_candidates": analysis.get("white_background_candidates", []),
                   "white_background": {"status": white_status, "candidates": assessments,
                                        "checked_at": now()},
                   "references": references,
                   "vision": dict(vision_meta, imported_at=now(), source_paths=[str(f) for f in files],
                                  conversions=notes)}
        atomic_json(task_dir(root, product) / PROFILE_FILE, profile)
        task = start_task(root, product, source_note="; ".join(str(f.parent) for f in files[:3]))
        task["state"] = "recognizing" if vision_meta["status"] == "complete" else "blocked"
        task["counts"]["vision_calls"] = vision_meta.get("calls", 0)
        save_task(root, product, task)
        if vision_meta.get("calls"):
            atomic_json(task_dir(root, product) / REQUESTS_FILE, [{
                "request_id": "vision-%s" % index, "kind": "vision", "stage": "recognize",
                "image_task_id": None, "status": "succeeded", "started_at": now(), "ended_at": now(),
                "meta": {"model": vision_meta.get("model")}, "usage": vision_meta.get("usage"), "cost": None
            } for index in range(1, vision_meta["calls"] + 1)])
        print("产品：%s" % product)
        print("原图：%d 张 → %s" % (len(references), product_dir(root, product, "01_原始素材")))
        print("识别：%s（%s 次调用）" % (vision_meta["status"], vision_meta.get("calls", 0)))
        if notes:
            print("格式转换：" + "；".join(notes))
        print("下一步：生成套图方案")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    main()
