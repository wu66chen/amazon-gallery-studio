#!/usr/bin/env python3
"""Plan a product gallery. Offline mode never claims to have seen image pixels."""

import argparse
import base64
import json
from pathlib import Path
import struct
import sys
import urllib.error
import urllib.request

from api_runtime import VISION_MODEL, credentials

MODEL = VISION_MODEL
GENERIC_ROLES = [
    ("Listing 副图", "商品主视觉", "清楚展示商品本体，背景和道具服务于商品"),
    ("Listing 副图", "生活场景", "展示合适且可信的使用环境"),
    ("Listing 副图", "可见细节", "放大参考图确实拍到的结构或纹理"),
    ("Listing 副图", "补充视角", "从不同景别补充理解商品，不重复前图"),
]


def suggested_roles(analysis):
    label = str(analysis.get("product_type", ""))
    facts = " ".join(str(value) for value in analysis.get("visible_facts", []))
    evidence = label + " " + facts
    if "圣诞树" in evidence and any(term in evidence for term in ("螺旋", "内芯", "外壳", "星")):
        return [
            ("Listing 副图", "完整造型主视觉", "以参考图中的完整组装状态为主角，做清晰、有节日气氛的桌面静物"),
            ("Listing 副图", "组合状态展示", "用参考图确实呈现的组合状态，清楚展示绿白螺旋造型与黄色星顶"),
            ("Listing 副图", "部件关系", "并列呈现参考图中的分离部件；只描述看得到的部件关系，不宣称未经验证的玩法"),
            ("Listing 副图", "组装过程画面", "依据参考图中出现的手部与不同状态，呈现可见的组合过程；不增加动作或结构"),
            ("Listing 副图", "3D 打印外观细节", "放大照片确实可见的逐层纹理和镂空螺旋表面，不推断塑料种类"),
            ("Listing 副图", "节日空间场景", "展示摆件在桌面或节日陈列中的比例感；不加入尺寸数字或虚构配件"),
        ]
    return GENERIC_ROLES


def dimensions(path):
    with path.open("rb") as f:
        header = f.read(24)
        if header[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", header[16:24])
    # JPEG marker walk: read only dimensions, not visual contents.
    with path.open("rb") as f:
        if f.read(2) != b"\xff\xd8":
            raise ValueError("not a JPEG or PNG")
        while True:
            marker = f.read(1)
            if not marker:
                break
            if marker != b"\xff":
                continue
            code = f.read(1)
            while code == b"\xff":
                code = f.read(1)
            if code in (b"\xd8", b"\xd9", b"\x00"):
                continue
            length = int.from_bytes(f.read(2), "big")
            if length < 2:
                break
            if code and code[0] in (0xC0, 0xC1, 0xC2, 0xC3):
                data = f.read(5)
                return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
            f.seek(length - 2, 1)
    raise ValueError("JPEG dimensions unavailable")


def recognize(images, key):
    instructions = (
        "Inspect EVERY supplied product photo. Respond ONLY with valid JSON containing keys "
        "product_type (string), visible_facts (array of strings), shared_structure (array), "
        "variants (array of objects with label, evidence, reference_index), unknowns (array), "
        "style_direction (string), style_reason (string), audience_hypothesis (string), "
        "confidence (low/medium/high). Do not infer measurements, composition, certification, "
        "included accessories or hidden views. Distinguish uncertain visual impressions from facts. "
        "Also include white_background_candidates (array of 1-based reference indices whose product appears on an unobstructed near-white background; only if visually clear). "
        "Use Chinese. The reference_index is the 1-based index of the input photo."
    )
    content = [{"type": "text", "text": instructions}]
    for index, image in enumerate(images, 1):
        mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
        encoded = base64.b64encode(image.read_bytes()).decode("ascii")
        content.append({"type": "text", "text": "Reference image %s" % index})
        content.append({"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (mime, encoded)}})
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": content}], "temperature": 0.1}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request("https://tokease.com/v1/chat/completions", data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as result:
        response = json.load(result)
    answer = response["choices"][0]["message"]["content"]
    if isinstance(answer, list):
        answer = "".join(part.get("text", "") for part in answer if isinstance(part, dict))
    answer = answer.strip()
    if answer.startswith("```"):
        answer = answer.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    analysis = json.loads(answer)
    if not isinstance(analysis.get("visible_facts"), list) or not isinstance(analysis.get("unknowns"), list):
        raise ValueError("visual response missing required facts or unknowns")
    return analysis, response.get("usage", {})


def escape(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def copy_suggestions(analysis):
    """Neutral editorial copy only; no inferred feature/performance claims."""
    if not analysis:
        return []
    product = str(analysis.get("product_type", "")).lower()
    if "圣诞" in product:
        return ["A LITTLE HOLIDAY MOMENT", "MADE FOR THE SEASON", "A FESTIVE DETAIL"]
    return ["THE DETAILS MATTER", "A CLOSER LOOK", "YOUR EVERYDAY EDIT"]


def build_rows(count, overrides, roles):
    rows = []
    for i in range(count):
        placement, purpose, composition = roles[i % len(roles)]
        if i >= len(roles):
            purpose = "补充视角 %d" % (i - len(roles) + 1)
            composition = "根据真实素材确定不同于已有图的画面"
        if str(i + 1) in overrides:
            user = overrides[str(i + 1)]
            placement = user.get("placement", placement)
            purpose = user.get("purpose", purpose)
            composition = user.get("composition", composition)
        rows.append((i + 1, placement, purpose, composition))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", nargs="+", type=Path, required=True, help="Explicit product photo files, not a recursive product folder")
    parser.add_argument("--output", type=Path, help="Record directory inside this project; defaults to 任务资产与审批/04_记录与报告")
    parser.add_argument("--count", type=int, help="Requested image count; omit to show an editable four-image suggestion")
    parser.add_argument("--roles", type=Path, help="JSON mapping of 1-based image numbers to placement/purpose/composition")
    parser.add_argument("--analysis-json", type=Path, help="Reuse an existing vision analysis without another model call")
    parser.add_argument("--product", help="User-supplied product description, attributed and not visually verified in offline mode")
    parser.add_argument("--copy-mode", choices=("ask", "none", "provided", "suggest"), default="ask",
                        help="Default ask: one copy decision before approval; never silently assume no text")
    parser.add_argument("--copy-text", help="User-supplied exact copy for a single image; requires --copy-mode provided")
    parser.add_argument("--white-bg", choices=("ask", "reuse", "generate", "none"), default="ask",
                        help="White-background main image choice; ask if existing source may be reusable")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="No paid call; visual identity unverified")
    mode.add_argument("--vision", action="store_true", help="Inspect source images with Tokease Gemini 3.5 Flash")
    args = parser.parse_args()
    if args.count is not None and args.count < 1:
        parser.error("count must be at least 1")
    if args.copy_mode == "provided" and not args.copy_text:
        parser.error("--copy-mode provided needs --copy-text")
    if args.copy_text and args.copy_mode != "provided":
        parser.error("--copy-text needs --copy-mode provided")
    images = [p.expanduser().resolve(strict=True) for p in args.images]
    if any(p.suffix.lower() not in (".jpg", ".jpeg", ".png") for p in images):
        parser.error("only JPG and PNG reference files are accepted")
    if len(images) > 8:
        parser.error("choose at most eight relevant product photos for one analysis")
    overrides = json.loads(args.roles.read_text(encoding="utf-8")) if args.roles else {}
    if not isinstance(overrides, dict) or any(not isinstance(v, dict) for v in overrides.values()):
        parser.error("roles must map image numbers to objects")
    proposed_roles = suggested_roles({})
    count = args.count or len(proposed_roles)
    if any(not k.isdigit() or int(k) < 1 or int(k) > count for k in overrides):
        parser.error("role numbers must be within the planned image count")
    files = []
    for path in images:
        files.append({"path": str(path), "pixels": dimensions(path)})
    analysis = None
    usage = {}
    error = ""
    model_used = MODEL if args.vision else None
    if args.analysis_json and args.vision:
        parser.error("use either --analysis-json or --vision, not both")
    if not args.analysis_json and not (args.vision or args.offline):
        parser.error("choose --vision, --offline, or --analysis-json")
    if args.analysis_json:
        saved = json.loads(args.analysis_json.read_text(encoding="utf-8"))
        analysis = saved.get("analysis")
        if not analysis:
            parser.error("analysis-json does not contain visual analysis")
        usage = saved.get("usage", {})
        model_used = saved.get("model") or MODEL
    elif args.vision:
        try:
            key = credentials()["key"]
        except ValueError as exc:
            parser.error(str(exc))
        try:
            analysis, usage = recognize(images, key)
        except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
            error = "%s: %s" % (type(exc).__name__, str(exc)[:240])
    proposed_roles = suggested_roles(analysis or {})
    if args.count is None:
        count = len(proposed_roles)
    status = "已分析（待人工核对）" if analysis else "未完成（仅有文件信息）"
    title = analysis.get("product_type") if analysis else (args.product or "未确认商品")
    style = analysis.get("style_direction", "待图像识别后再确定") if analysis else "待图像识别后再确定"
    rows = build_rows(count, overrides, proposed_roles)
    suggestions = copy_suggestions(analysis)
    copy_status = {
        "ask": "待用户选择", "none": "明确无文案", "provided": "用户已提供", "suggest": "建议文案待确认",
    }[args.copy_mode]
    per_image_copy = []
    for number, placement, _, _ in rows:
        if "Listing 首图" in placement:
            per_image_copy.append({"number": number, "status": "不适合加文案", "text": ""})
        elif args.copy_mode == "provided":
            per_image_copy.append({"number": number, "status": "用户已提供", "text": args.copy_text})
        else:
            per_image_copy.append({"number": number, "status": copy_status, "text": ""})
    project = Path(__file__).resolve().parents[1]
    records = (project / "任务资产与审批/04_记录与报告").resolve()
    out = args.output.expanduser().resolve() if args.output else records
    out.mkdir(parents=True, exist_ok=True)
    candidates = analysis.get("white_background_candidates", []) if analysis else []
    white_needs_choice = args.white_bg == "ask" and bool(candidates)
    report = {"recognition_status": status, "model": model_used, "vision_error": error, "product_label": title, "user_supplied_product": args.product, "images": files, "analysis": analysis, "usage": usage, "rows": [{"number": n, "placement": p, "purpose": u, "composition": c} for n,p,u,c in rows], "copy": {"mode": args.copy_mode, "status": copy_status, "suggestions": suggestions, "images": per_image_copy, "confirmed": args.copy_mode in ("none", "provided")}, "white_background": {"mode": "none" if args.white_bg == "ask" and not candidates else args.white_bg, "candidates": candidates, "confirmed": not white_needs_choice}, "confirmed": False}
    record_name = "商品识别与方案_%s" % (args.product or title or "未命名商品").replace("/", "-").replace("\\", "-")
    (out / (record_name + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 套图建议 · 待确认", "", "> 商品：%s ｜ 视觉识别：%s ｜ 建议 %d 张" % (escape(title), status, count), "", "**视觉方向：**%s" % escape(style), "", "| # | 发布用途 | 展示任务 | 画面建议 | 文案 |", "|---|---|---|---|---|"]
    lines += ["| %02d | %s | %s | %s | %s |" % (n, escape(p), escape(u), escape(c), escape(per_image_copy[n-1]["status"])) for n,p,u,c in rows]
    lines += ["", "**待确认：**张数与逐张用途；可以整套采用或修改任意一行。", "", "**素材事实：**"]
    if args.copy_mode == "ask":
        lines += ["", "**文案选择：**你还没有指定图片文案，请回复一个选项：", "- **1**：你提供每张图的文案（可以只提供需要文字的图片编号）。", "- **2**：我按产品事实提出逐图文案建议，确认后再使用。", "- **不要文案**：整套副图都不添加文字。", "可回复 `1`、`2` 或 `不要文案`。发布用途为 Amazon Listing 首图的图片始终无文案。"]
    elif args.copy_mode == "suggest":
        lines += ["", "**可选的中性文案方向（待确认，不自动写入图片）：**"] + ["- %s" % s for s in suggestions[:3]]
    if args.white_bg == "ask" and candidates:
        lines += ["", "**白底图选择：**参考图 %s 看起来可作白底候选（尚未通过 Amazon 合规检查）。本套是否还要生成新的白底图？回复 `沿用现有`、`生成新的` 或 `不需要白底`。" % ", ".join(str(i) for i in candidates)]
    if analysis:
        lines += ["- %s" % escape(v) for v in analysis.get("visible_facts", [])]
        lines += ["**仍不确定：**"] + ["- %s" % escape(v) for v in analysis.get("unknowns", [])]
    else:
        lines.append("- 原图 %d 张，已读取尺寸；尚未可靠识别外观。" % len(files))
        if args.product:
            lines.append("- 用户称此商品为「%s」，尚未通过视觉确认。" % escape(args.product))
        lines.append("- 商品颜色、结构、尺寸、场景和设计风格仍待视觉识别；以上逐张任务仅为可修改的占位建议。")
    plan_name = "方案摘要_%s.md" % (args.product or title or "未命名商品").replace("/", "-").replace("\\", "-")
    (out / plan_name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("识别：%s｜建议：%d 张｜下一步：确认或修改套图方案" % (status, count))
    print("方案摘要：%s" % (out / plan_name))
    if error:
        print("视觉识别失败，已降级：%s" % error, file=sys.stderr)


if __name__ == "__main__":
    main()
