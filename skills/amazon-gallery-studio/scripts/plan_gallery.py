#!/usr/bin/env python3
"""Turn a recognized product into a frozen, approvable gallery plan (vNext)."""

import argparse
import json
from pathlib import Path

from ags_core import (AgsError, PLAN_FILE, PROFILE_FILE, atomic_json, choose_representative,
                      load_task, now, plan_cost_text, plan_digest, read_json, resolve_product,
                      save_task, set_state, task_dir)
from api_runtime import workspace

MAIN_USAGE = "Amazon MAIN 首图"


def load_profile(root, product):
    profile = read_json(task_dir(root, product) / PROFILE_FILE)
    if not profile:
        raise AgsError("缺少产品识别档案，请先运行 import_assets.py")
    return profile


def role_library(profile, count, include_main):
    variants = profile.get("variants", []) or []
    features = profile.get("structural_features", []) or []
    roles = []
    if include_main:
        roles.append({"usage": MAIN_USAGE, "purpose": "官方 MAIN 首图",
                      "scene": "纯白背景，仅商品", "composition": "产品居中，完整清晰，占画面约 85%"})
    roles.append({"usage": "Listing 副图", "purpose": "商品主视觉",
                  "scene": "干净的商业摄影背景，不过度布景", "composition": "完整商品，突出轮廓与比例"})
    if variants:
        roles.append({"usage": "Listing 副图", "purpose": "配色与款式集合",
                      "scene": "统一视觉体系下的陈列静物", "composition": "所有真实配色同时出现，数量与参考一致"})
        roles.append({"usage": "Listing 副图", "purpose": "单色使用场景",
                      "scene": "符合商品用途的真实生活场景", "composition": "选一个有代表性的真实配色，产品为画面主角"})
    else:
        roles.append({"usage": "Listing 副图", "purpose": "使用场景",
                      "scene": "符合商品用途的真实生活场景", "composition": "产品为主角，人物仅作为尺度与使用情境"})
    roles.append({"usage": "Listing 副图", "purpose": "可见细节",
                  "scene": "近景产品摄影", "composition": "放大参考图确实拍到的结构、纹理或工艺"})
    if features:
        roles.append({"usage": "Listing 副图", "purpose": "结构与角度",
                      "scene": "中性背景的产品角度图", "composition": "展示参考图可确认的另一视角或结构"})
    roles.append({"usage": "Listing 副图", "purpose": "比例与场景关系",
                  "scene": "有参照物的真实空间", "composition": "用环境尺度帮助理解大小，不添加虚构尺寸数字"})
    roles.append({"usage": "广告/站外图", "purpose": "品牌氛围收束",
                  "scene": "更概念化的摄影场景", "composition": "统一色彩与光影，适合广告或社媒"})
    while len(roles) < count:
        roles.append({"usage": "Listing 副图", "purpose": "补充场景 %d" % (len(roles) + 1),
                      "scene": "与已有图片不同的真实场景", "composition": "避免重复构图，提供新的信息价值"})
    return roles[:count]


def default_copy(mode, text):
    if mode == "none":
        return {"status": "none", "text": "", "candidates": []}
    if mode == "provided":
        if not text:
            raise AgsError("--copy-mode provided 需要 --copy-text")
        return {"status": "user_provided", "text": text, "candidates": []}
    if mode == "suggest":
        return {"status": "suggested_pending", "text": "",
                "candidates": ["A CLOSER LOOK", "MADE FOR EVERYDAY USE", "THE DETAILS MATTER"]}
    return {"status": "pending", "text": "", "candidates": []}


def load_requirements(path):
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AgsError("--requirements 必须是 JSON 对象")
    unknown = set(data) - {"count", "ratio", "size", "copy_mode", "images"}
    if unknown:
        raise AgsError("未知需求字段：%s" % "、".join(sorted(unknown)))
    return data


def white_candidates(profile):
    return list((profile.get("white_background") or {}).get("candidates") or [])


def best_white(profile, verdicts=("reuse",)):
    variants = [v for v in (profile.get("variants") or []) if isinstance(v, dict)]
    if len(variants) > 1:
        return None
    for candidate in sorted(white_candidates(profile), key=lambda c: c.get("reference_index", 999)):
        if candidate.get("verdict") in verdicts:
            return candidate
    return None


def candidate_fits(candidate, ratio, size):
    """Check whether a reuse candidate matches the requested ratio and pixel target."""
    technical = candidate.get("technical", {})
    width, height = technical.get("width"), technical.get("height")
    if not width or not height:
        return False, "缺少候选尺寸信息"
    try:
        left, right = [float(part) for part in str(ratio).split(":")]
        if abs((width / height) - (left / right)) / (left / right) > 0.02:
            return False, "候选比例与目标 %s 不符，需要修整" % ratio
    except (ValueError, ZeroDivisionError):
        return False, "目标比例格式无效"
    try:
        target_w, target_h = [int(part) for part in str(size).lower().split("x")]
    except ValueError:
        return False, "目标像素格式无效"
    if width < target_w or height < target_h:
        return False, "候选像素低于目标 %s，放大不能替代真实细节" % size
    return True, ""


def white_decision(profile, requested, include_main, explicit_main, explicit_images=False,
                   ratio="1:1", size="1024x1024"):
    candidates = white_candidates(profile)
    why = ""
    reusable = best_white(profile)
    retouchable = best_white(profile, ("retouch",))
    status = (profile.get("white_background") or {}).get("status", "none")
    has_main = bool(include_main or explicit_main or requested in ("reuse", "retouch", "generate"))
    if requested == "auto" and reusable:
        has_main = True
    if explicit_images and not explicit_main and requested == "auto":
        has_main = False
    if requested == "none":
        has_main = bool(include_main or explicit_main)
    if requested == "reuse":
        if not reusable:
            raise AgsError("你要求复用现有白底图，但没有通过检查的可复用候选；请改用 --white-bg retouch/generate/none")
        fits, why = candidate_fits(reusable, ratio, size)
        if not fits:
            raise AgsError("现有候选不能直接复用：%s；请改用 --white-bg retouch" % why)
        choice, render, selected = "reuse", "reuse", reusable
    elif requested == "retouch":
        if not retouchable:
            raise AgsError("你要求修整白底图，但没有可修整候选；请改用 generate 或 none")
        choice, render, selected = "retouch", "retouch", retouchable
    elif requested == "generate":
        choice, render, selected = "generate", "generate", None
    elif requested == "none":
        choice, render, selected = "none", "generate", None
    else:  # auto
        if reusable:
            fits, why = candidate_fits(reusable, ratio, size)
            if fits:
                choice, render, selected = "reuse", "reuse", reusable
            else:
                choice, render, selected = "retouch", "retouch", reusable
        elif has_main:
            choice, render, selected = ("retouch", "retouch", retouchable) if retouchable else ("generate", "generate", None)
        else:
            choice, render, selected = "none", None, None
    if not has_main:
        choice, render, selected = "none", None, None
    reason = {
        "reuse": "已发现通过技术检查与视觉评估的白底候选，复用可节省一次生图调用。",
        "retouch": "白底候选存在可修复问题（比例/背景边缘/构图/像素），建议付费修整并保留原图。",
        "generate": "没有可直接复用或修整的白底候选，建议为新 MAIN 生成一张。",
        "none": "本套不包含白底 MAIN；现有候选不影响其他图片。",
    }[choice]
    if why:
        reason += " " + why
    if len(profile.get("variants") or []) > 1 and choice == "reuse":
        reason += " 候选颜色：%s。" % selected.get("variant_label", "未标注")
    return {"recommendation": choice, "choice": choice, "render": render,
            "selected": selected, "candidates": candidates, "status": status,
            "reason": reason, "has_main": has_main,
            "source": "user_locked" if requested != "auto" else "agent_proposed"}


def compute_counts(images):
    reused = sum(1 for t in images if t.get("render") == "reuse")
    retouch = sum(1 for t in images if t.get("render") == "retouch")
    generated = sum(1 for t in images if t.get("render") == "generate")
    return {"total": len(images), "reused": reused, "retouch": retouch, "generated": generated,
            "paid": retouch + generated}


def build_plan(profile, args, requirements=None):
    requirements = requirements or {}
    count = args.count or requirements.get("count") or 6
    if count < 1 or count > 20:
        raise AgsError("张数需在 1–20 之间")
    ratio = requirements.get("ratio", args.ratio)
    size = requirements.get("size", args.size)
    copy_mode = requirements.get("copy_mode", args.copy_mode)
    explicit_images = requirements.get("images", []) or []
    explicit_main = any(str(item.get("usage", "")).startswith("Amazon MAIN") for item in explicit_images if isinstance(item, dict))
    white = white_decision(profile, args.white_bg, args.include_main, explicit_main, bool(explicit_images),
                           ratio, size)
    roles = role_library(profile, count, white["has_main"])
    copy = default_copy(copy_mode, args.copy_text)
    references = profile.get("references", [])
    variants = profile.get("variants", []) or []
    images = []
    white_assigned = False
    for index, role in enumerate(roles, 1):
        refs = references
        if role["purpose"] == "单色使用场景" and variants:
            variant_index = int(variants[0].get("reference_index", 1)) - 1
            if 0 <= variant_index < len(references):
                refs = [references[variant_index]]
        task_copy = dict(copy)
        render = "generate"
        reuse_id = None
        if role["usage"] == MAIN_USAGE:
            task_copy = {"status": "not_applicable", "text": "", "candidates": []}
            if white["render"] and not white_assigned:
                render = white["render"]
                reuse_id = (white["selected"] or {}).get("reference_id")
                if render == "reuse" and reuse_id:
                    refs = [next(r for r in references if r["reference_id"] == reuse_id)]
                white_assigned = True
        images.append({
            "id": "img-%02d" % index, "display_number": index, "usage": role["usage"],
            "purpose": role["purpose"], "scene": role["scene"], "composition": role["composition"],
            "aspect_ratio": ratio, "pixel_target": size, "copy": task_copy, "render": render,
            "reuse_reference": reuse_id,
            "references": ([r["reference_id"] for r in refs] if refs else (["R01"] if references else [])),
            "constraints": ["仅使用已确认的商品事实", "不添加未确认的配件或性能"],
            "quality_checks": ["technical", "visual"],
        })
    for override in explicit_images:
        if not isinstance(override, dict) or not isinstance(override.get("number"), int):
            raise AgsError("requirements.images 每项必须包含数字 number")
        target = next((t for t in images if t["display_number"] == override["number"]), None)
        if not target:
            raise AgsError("requirements.images 的编号超出计划张数：%s" % override["number"])
        for key in ("usage", "purpose", "scene", "composition"):
            if isinstance(override.get(key), str) and override[key].strip():
                target[key] = override[key].strip()
        if override.get("ratio"):
            target["aspect_ratio"] = override["ratio"]
        if override.get("size"):
            target["pixel_target"] = override["size"]
        if override.get("copy"):
            target["copy"] = {"status": "user_provided", "text": str(override["copy"]), "candidates": []}
        if override.get("references"):
            target["references"] = list(override["references"])
    if any(t["copy"]["status"] == "user_provided" for t in images):
        copy_mode = "provided"
    counts = compute_counts(images)
    paid = [t for t in images if t.get("render") != "reuse"]
    representative = choose_representative(paid) if paid else None
    plan = {
        "version": 1, "created_at": now(), "product_name": profile["product_name"],
        "product": profile, "images": images,
        "requirements": {
            "count": {"value": count, "source": "user_locked" if args.count else "agent_proposed"},
            "aspect_ratio": {"value": ratio, "source": "user_locked" if ratio != "1:1" or requirements else "default"},
            "pixel_target": {"value": size, "source": "user_locked" if size != "1024x1024" or requirements else "default"},
            "copy_mode": {"value": copy_mode, "source": "user_locked" if copy_mode != "ask" else "agent_proposed"},
            "white_background": {"value": white["choice"], "source": white["source"]},
        },
        "design": {"direction": "自然、干净、现代商业摄影", "palette": "从真实商品配色中提取",
                   "lighting": "柔和定向光，真实接触阴影", "typography": "仅在用户批准文案时使用"},
        "white_background": {"recommendation": white["recommendation"], "choice": white["choice"],
                             "confirmed": False, "status": white["status"],
                             "selected_reference_id": (white["selected"] or {}).get("reference_id"),
                             "reason": white["reason"], "candidates": white["candidates"],
                             "counts": counts},
        "counts": counts,
        "cost_quote": {"status": "unavailable", "amount_usd": None,
                       "max_image_calls": counts["paid"] + 5,
                       "basis": "复用图片不计费；仅对需要生成/修整的图片计算调用；未提供可核验单价"},
        "representative_task_id": representative["id"] if representative else None,
    }
    if args.price_per_image is not None:
        if args.price_per_image < 0:
            raise AgsError("单价不能为负")
        plan["cost_quote"].update({"status": "estimated",
                                    "amount_usd": round(args.price_per_image * counts["paid"], 4),
                                    "basis": "用户提供的每张生图价格 × 需付费图片数（复用不计费）；估算≠最终账单"})
    plan["plan_hash"] = plan_digest(plan)
    return plan


def brief(plan, profile):
    wb = plan["white_background"]
    counts = plan["counts"]
    lines = ["# 套图方案｜%s" % plan["product_name"], "",
             "共 %d 张｜%s｜%s｜原图 %d 张" % (counts["total"], plan["requirements"]["aspect_ratio"]["value"],
                                              plan["requirements"]["pixel_target"]["value"],
                                              len(profile.get("references", []))),
             "构成：复用 %d 张｜修整 %d 张｜新生成 %d 张｜需付费 %d 张"
             % (counts["reused"], counts["retouch"], counts["generated"], counts["paid"]),
             "视觉方向：%s" % plan["design"]["direction"], ""]
    for task in plan["images"]:
        copy_status = {"none": "无文案", "user_provided": "用户文案", "suggested_pending": "建议文案待确认",
                       "pending": "文案待选择", "not_applicable": "不适用"}.get(task["copy"]["status"], task["copy"]["status"])
        source = {"reuse": "复用原图", "retouch": "付费修整", "generate": "新生成"}[task.get("render", "generate")]
        lines.append("%02d %s：%s（%s；%s · %s；%s）"
                     % (task["display_number"], task["purpose"], task["scene"], source, task["aspect_ratio"],
                        task["pixel_target"], copy_status))
    lines.append("")
    if wb["choice"] == "reuse":
        selected = next((c for c in wb["candidates"] if c.get("reference_id") == wb.get("selected_reference_id")), None)
        lines += ["**白底主图：发现 1 张可复用候选（%s）**" % (selected or {}).get("reference_id", "?"),
                  "推荐：直接采用原图，节省一次生图费用。",
                  "白A. 复用现有白底图（推荐）｜白B. 重新生成一张｜白C. 本次不纳入白底图"]
    elif wb["choice"] == "retouch":
        lines += ["**白底主图：发现需修整的候选**", "原因：%s" % wb["reason"],
                  "白A. 修整现有白底图（付费编辑）｜白B. 重新生成一张｜白C. 本次不纳入白底图"]
    elif wb["choice"] == "generate":
        lines += ["**白底主图：未发现可直接复用的合格图**", "建议：新生成一张 MAIN 主图。",
                  "白A. 新生成一张白底主图（推荐）｜白B. 本次不纳入白底图"]
    else:
        lines += ["**白底主图：本次不纳入**", wb["reason"]]
    lines += ["", "代表图：%s" % (
        "将先制作第 %02d 张「%s」，用于验证商品保真与视觉方向。" % (
            next(t for t in plan["images"] if t["id"] == plan["representative_task_id"])["display_number"],
            next(t for t in plan["images"] if t["id"] == plan["representative_task_id"])["purpose"])
        if plan.get("representative_task_id") else "本套均为原图复用，无需生成代表图。"),
        "", "费用：%s" % plan_cost_text(plan), "价格依据：%s" % plan["cost_quote"]["basis"],
        "", "确认后才会调用你的 API Key 生图，产生真实费用。",
        "", "1. 按本方案执行（回复 1；白底选项如无异议一并确认）",
        "2. 修改指定编号或要求", "3. 更换风格方向"]
    if plan["requirements"]["copy_mode"]["value"] == "ask":
        lines += ["", "文案：尚未确定。可回复 `1` 由你提供、`2` 让我建议、`不要文案`。"]
    lines += ["", "> 复用图必须通过技术与视觉检查；自动判断不等于 Amazon 平台审核通过，MAIN 规则以目标站点/类目为准。"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--product")
    parser.add_argument("--count", type=int)
    parser.add_argument("--ratio", default="1:1")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--copy-mode", choices=("ask", "none", "provided", "suggest"), default="ask")
    parser.add_argument("--copy-text")
    parser.add_argument("--white-bg", choices=("auto", "reuse", "retouch", "generate", "none", "ask"),
                        default="auto", help="auto recommends reuse when a checked candidate exists")
    parser.add_argument("--include-main", action="store_true")
    parser.add_argument("--price-per-image", type=float)
    parser.add_argument("--requirements", type=Path)
    args = parser.parse_args()
    if args.white_bg == "ask":
        args.white_bg = "auto"
    try:
        root = workspace(args.workspace)
        product = resolve_product(root, args.product)
        profile = load_profile(root, product)
        plan = build_plan(profile, args, load_requirements(args.requirements))
    except (AgsError, ValueError) as exc:
        parser.error(str(exc))
    directory = task_dir(root, product)
    atomic_json(directory / PLAN_FILE, plan)
    (directory / "方案简报.md").write_text(brief(plan, profile), encoding="utf-8")
    task = load_task(root, product)
    task["plan_version"] = plan["version"]
    task["plan_hash"] = plan["plan_hash"]
    task["representative_task_id"] = plan["representative_task_id"]
    save_task(root, product, task)
    set_state(root, product, "plan_pending_approval")
    print(brief(plan, profile))
    print("方案记录：%s" % (directory / PLAN_FILE))


if __name__ == "__main__":
    main()
