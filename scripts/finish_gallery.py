#!/usr/bin/env python3
"""After representative approval, generate remaining images and deliver one final folder."""

import argparse
import base64
import json
from pathlib import Path
import re
import urllib.request

from api_runtime import BASE_URL, IMAGE_MODEL, VISION_MODEL, credentials
from gallery_workflow import paths, remaining_tasks


def decode_answer(answer):
    if isinstance(answer, list):
        answer = "".join(x.get("text", "") for x in answer if isinstance(x, dict))
    text = str(answer).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def white_reference(plan, row, original):
    """Select a source for an approved reuse choice, never invent a white main."""
    choice = plan.get("white_background", {})
    if choice.get("mode") != "reuse" or "Listing 首图" not in row.get("placement", ""):
        return None
    candidates = choice.get("candidates", [])
    if not candidates:
        raise ValueError("没有经过视觉识别的白底候选图，不能沿用现有")
    index = choice.get("reference_index", candidates[0])
    if not isinstance(index, int) or index not in candidates:
        raise ValueError("白底候选编号未确认")
    originals = plan.get("images", [])
    if index > len(originals):
        raise ValueError("找不到所选白底候选图对应的素材记录")
    source = original / Path(originals[index - 1]["path"]).name
    if not source.is_file():
        raise ValueError("白底候选原图未导入当前套图")
    return source


def review(image, refs, identity, task, key):
    content = [{"type": "text", "text": "Compare candidate to source images. Identify product changes, text mistakes, and whether it fulfills task: %s. Product facts: %s. Return JSON with status pass/revise/uncertain, issues array, evidence string. If ambiguous mark uncertain." % (task, identity)}]
    for label, path in [("Original %d" % (i + 1), p) for i, p in enumerate(refs)] + [("Candidate", image)]:
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        content.extend(({"type": "text", "text": label}, {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode())}}))
    body = json.dumps({"model": VISION_MODEL, "messages": [{"role": "user", "content": content}], "temperature": 0}).encode()
    req = urllib.request.Request(BASE_URL + "/chat/completions", data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as result:
        response = json.load(result)
    return decode_answer(response["choices"][0]["message"]["content"])


def run(plan, set_name, *, execute=False):
    original, approval, final, records = paths(set_name)
    if not plan.get("representative_approved"):
        raise ValueError("代表图未获批准；不得批量生成")
    representative = Path(plan["representative_file"]).resolve(strict=True)
    if representative.parent != final.resolve():
        raise ValueError("代表图必须已归档在本项目最终套图目录")
    refs = sorted(p for p in original.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not refs:
        raise ValueError("缺少本项目原始素材")
    tasks = remaining_tasks(plan)
    if not execute:
        return {"status": "dry-run", "remaining": len(tasks), "tasks": tasks}
    if not plan.get("confirmed") or not plan.get("cost_estimate_approved"):
        raise ValueError("套图方案与预估费用尚未获批准")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ValueError("缺少 openai Python SDK；请先安装项目依赖") from exc
    key = credentials()["key"]
    client = OpenAI(api_key=key, base_url=BASE_URL)
    identity = "; ".join(plan.get("analysis", {}).get("visible_facts", []))
    results = []
    for row in tasks:
        number = row["number"]
        purpose = row["purpose"]
        label = re.sub(r"[^\w\u4e00-\u9fff-]", "", purpose)[:30] or "商品图"
        output = final / ("%02d_%s.png" % (number, label))
        if output.exists():
            raise ValueError("已有同名图片，暂停以免覆盖：%s" % output.name)
        reusable = white_reference(plan, row, original)
        if reusable:
            from PIL import Image
            with Image.open(reusable) as source:
                rgb = source.convert("RGB")
                corners = (rgb.getpixel((0, 0)), rgb.getpixel((rgb.width - 1, 0)),
                           rgb.getpixel((0, rgb.height - 1)), rgb.getpixel((rgb.width - 1, rgb.height - 1)))
                if any(pixel != (255, 255, 255) for pixel in corners):
                    raise ValueError("现有白底候选的角落不是纯白；请人工确认或选择生成新白底图")
                if min(rgb.size) < 1000:
                    raise ValueError("现有白底候选分辨率不足，不能直接当作 Amazon 首图")
                rgb.save(output)
            qa = {"status": "uncertain", "issues": ["沿用参考图：纯白角落与像素通过；商品占比、杂物及类目规则待人工确认"]}
            results.append({"number": number, "file": output.name, "qa": qa})
            (records / ("质检_%s_%02d.json" % (set_name, number))).write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            continue
        main_image = "Listing 首图" in row.get("placement", "")
        prompt = ("Edit the supplied authentic product photo into a photorealistic Amazon product image. "
                  "Preserve product identity exactly: %s. Role: %s. Composition: %s. "
                  "Maintain the approved representative image's color palette and premium photography style. "
                  "No invented parts, claims, measurements, labels or included accessories. "
                  "Only use verified product details. %s %s" % (identity, purpose, row["composition"],
                   "Pure white RGB 255,255,255, product only, no props, no overlays." if main_image else "",
                   "No added copy." if main_image or not row.get("copy") else "Use exact approved copy: " + row["copy"]))
        try:
            with refs[0].open("rb") as source:
                response = client.images.edit(model=IMAGE_MODEL, image=source, prompt=prompt, size="1024x1024", quality="high", output_format="png")
            if not response.data or not response.data[0].b64_json:
                raise ValueError("图像接口没有返回图片")
            output.write_bytes(base64.b64decode(response.data[0].b64_json))
            from PIL import Image
            with Image.open(output) as generated:
                if generated.width != generated.height or min(generated.size) < 1000:
                    qa = {"status": "revise", "issues": ["实际图片未达到 1:1 或 1000px 最低边长"]}
                else:
                    try:
                        qa = review(output, refs[:4], identity, purpose, key)
                    except Exception as exc:
                        qa = {"status": "uncertain", "issues": ["视觉初筛不可用：%s" % type(exc).__name__]}
        except Exception as exc:
            qa = {"status": "revise", "issues": ["生图调用失败：%s" % type(exc).__name__]}
            results.append({"number": number, "file": None, "qa": qa})
            break
        results.append({"number": number, "file": output.name, "qa": qa})
        (records / ("质检_%s_%02d.json" % (set_name, number))).write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if qa.get("status") != "pass":
            break
    (records / ("生成记录_%s.json" % set_name)).write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status = "needs-review" if len(results) != len(tasks) or any(x["qa"].get("status") != "pass" for x in results) else "generated"
    if len(results) == len(tasks):
        from PIL import Image, ImageDraw
        gallery = [representative] + [final / item["file"] for item in results if item["file"]]
        thumb, gap, cols = 360, 20, 3
        rows_count = (len(gallery) + cols - 1) // cols
        board = Image.new("RGB", (cols * (thumb + gap) + gap, rows_count * (thumb + 52 + gap) + gap), "#f5f2ed")
        draw = ImageDraw.Draw(board)
        for index, image in enumerate(gallery):
            with Image.open(image) as source:
                tile = source.convert("RGB")
                tile.thumbnail((thumb, thumb))
            x = gap + (index % cols) * (thumb + gap)
            y = gap + (index // cols) * (thumb + 52 + gap)
            board.paste(tile, (x + (thumb - tile.width) // 2, y))
            draw.text((x + 8, y + thumb + 12), "%02d" % (index + 1), fill="#172a25")
        board.save(final / "套图总览.jpg", quality=94)
        (final / "最终审核报告.md").write_text(
            "# 套图审核报告\n\n状态：待用户终审；机器初筛不能代替人工确认。\n\n"
            + "\n".join("- %02d %s：%s" % (item["number"], item["file"], item["qa"].get("status", "uncertain")) for item in results)
            + "\n", encoding="utf-8")
    return {"status": status, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-name", required=True)
    parser.add_argument("--plan", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true", help="Paid calls: requires user's accepted gallery estimate")
    args = parser.parse_args()
    original, approval, final, records = paths(args.set_name)
    plan_file = args.plan.resolve(strict=True)
    if plan_file.parent != records.resolve():
        parser.error("方案必须在本项目 04_记录与报告")
    try:
        result = run(json.loads(plan_file.read_text(encoding="utf-8")), args.set_name, execute=args.execute)
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
