#!/usr/bin/env python3
"""Shared state, asset, approval, cost and image utilities for Amazon Listing Images Skill."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import tempfile
import time
import uuid

from PIL import Image, ImageFilter, ImageStat

CATEGORIES = ("01_原始素材", "02_代表图审批", "03_最终套图", "04_记录与报告")
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
STATE_FILE = "task.json"
PLAN_FILE = "gallery-plan.json"
PROFILE_FILE = "product-profile.json"
APPROVALS_FILE = "approvals.json"
REQUESTS_FILE = "api-requests.json"


class AgsError(Exception):
    """A user-actionable workflow error."""


class BudgetError(AgsError):
    """A paid call would exceed the authorized limit."""


def now():
    return datetime.now(timezone.utc).isoformat()


def product_dir(root, product, category):
    return Path(root) / "任务资产与审批" / category / product


def task_dir(root, product):
    return product_dir(root, product, "04_记录与报告")


def ensure_product(root, product):
    for category in CATEGORIES:
        product_dir(root, product, category).mkdir(parents=True, exist_ok=True)


def safe_name(value, fallback="未命名商品"):
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "", str(value or "")).strip().strip(".")
    text = re.sub(r"\s+", " ", text)
    return text[:60] or fallback


def unique_product_name(root, base):
    name, index = safe_name(base), 1
    while any(product_dir(root, name, category).exists() for category in CATEGORIES):
        index += 1
        name = "%s_%02d" % (safe_name(base), index)
    return name


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def read_json(path, default=None):
    path = Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AgsError("记录文件损坏：%s（%s）" % (path, exc.msg))


def canonical_hash(data):
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


RUNTIME_IMAGE_KEYS = {"status", "versions", "approved_version_file", "approved_sha256", "final_file"}


def plan_digest(plan):
    """Hash only the approved design content, not runtime progress fields."""
    images = [{key: value for key, value in task.items() if key not in RUNTIME_IMAGE_KEYS}
              for task in plan.get("images", [])]
    payload = {key: plan.get(key) for key in ("version", "product", "requirements", "design",
                                              "white_background", "cost_quote", "representative_task_id")}
    payload["images"] = images
    return canonical_hash(payload)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _Lock:
    def __init__(self, path, timeout=60):
        self.path, self.timeout = Path(path), timeout

    def __enter__(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 600:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() > deadline:
                    raise AgsError("该套图正在被另一个进程处理，请稍后重试")
                time.sleep(0.2)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def lock(root, product):
    task_dir(root, product).mkdir(parents=True, exist_ok=True)
    return _Lock(task_dir(root, product) / ".lock")


def load_task(root, product):
    task = read_json(task_dir(root, product) / STATE_FILE)
    if not task:
        raise AgsError("找不到产品任务：%s" % product)
    return task


def save_task(root, product, task):
    task["updated_at"] = now()
    atomic_json(task_dir(root, product) / STATE_FILE, task)


def start_task(root, product, source_note=""):
    ensure_product(root, product)
    task = {
        "task_id": str(uuid.uuid4()),
        "product_name": product,
        "state": "importing",
        "created_at": now(),
        "updated_at": now(),
        "source_note": source_note,
        "plan_version": 0,
        "plan_hash": None,
        "representative_task_id": None,
        "budget": {"authorized_image_calls": 0, "used_image_calls": 0,
                   "authorized_total_cost_usd": None, "quote_status": "unavailable"},
        "counts": {"generated": 0, "vision_calls": 0, "rework_calls": 0},
        "resume": {"last_error": None, "pending_request": None},
    }
    save_task(root, product, task)
    return task


def set_state(root, product, state, error=None):
    task = load_task(root, product)
    task["state"] = state
    task["resume"]["last_error"] = error
    save_task(root, product, task)
    return task


def list_products(root):
    base = Path(root) / "任务资产与审批" / "04_记录与报告"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / STATE_FILE).is_file())


def resolve_product(root, name=None):
    if name:
        return name
    products = list_products(root)
    if not products:
        raise AgsError("还没有任何套图任务，请先导入商品原图")
    if len(products) > 1:
        raise AgsError("当前工作区有多套任务，请用 --product 指定：" + "、".join(products))
    return products[0]


# --- approvals -------------------------------------------------------------

def approvals(root, product):
    return read_json(task_dir(root, product) / APPROVALS_FILE, []) or []


def append_approval(root, product, **fields):
    record = {
        "approval_id": str(uuid.uuid4()),
        "task_id": load_task(root, product)["task_id"],
        "approved_at": now(),
    }
    record.update(fields)
    items = approvals(root, product)
    items.append(record)
    atomic_json(task_dir(root, product) / APPROVALS_FILE, items)
    return record


def latest_approval(root, product, stage):
    for item in reversed(approvals(root, product)):
        if item.get("stage") == stage and item.get("decision") == "approved":
            return item
    return None


def plan_record(root, product):
    return read_json(task_dir(root, product) / PLAN_FILE)


def require_plan_approval(root, product):
    plan = plan_record(root, product)
    if not plan:
        raise AgsError("尚未生成套图方案")
    expected = plan_digest(plan)
    if plan.get("plan_hash") != expected:
        raise AgsError("方案内容与保存的哈希不一致，可能被手动修改；请重新生成并确认方案")
    approval = latest_approval(root, product, "plan")
    if not approval:
        raise AgsError("套图方案尚未获得用户确认，不能调用付费生图")
    if approval.get("plan_hash") != plan.get("plan_hash") or approval.get("plan_version") != plan.get("version"):
        raise AgsError("方案已变化，请重新确认后再生成")
    return plan, approval


def require_representative_approval(root, product):
    plan, plan_approval = require_plan_approval(root, product)
    approval = latest_approval(root, product, "representative")
    if not approval:
        raise AgsError("代表图尚未获得用户批准")
    if approval.get("plan_hash") != plan.get("plan_hash"):
        raise AgsError("代表图批准对应的方案版本已变化，请重新确认")
    if approval.get("representative_image_id") != plan.get("representative_task_id"):
        raise AgsError("代表图批准与当前方案的代表图编号不一致")
    return plan, plan_approval, approval


def authorized_calls(root, product):
    plan_approval = latest_approval(root, product, "plan")
    extra = [a for a in approvals(root, product) if a.get("stage") == "extra_cost" and a.get("decision") == "approved"]
    total = int(plan_approval.get("authorized_image_calls", 0)) if plan_approval else 0
    total += sum(int(a.get("authorized_image_calls", 0)) for a in extra)
    return total


# --- request ledger and cost guard ----------------------------------------

def requests(root, product):
    return read_json(task_dir(root, product) / REQUESTS_FILE, []) or []


def write_requests(root, product, items):
    atomic_json(task_dir(root, product) / REQUESTS_FILE, items)


def reserve_paid_call(root, product, *, kind, stage, image_task_id=None, meta=None):
    with lock(root, product):
        task = load_task(root, product)
        if stage == "representative":
            require_plan_approval(root, product)
        elif stage == "batch":
            require_representative_approval(root, product)
        allowance = authorized_calls(root, product)
        used = int(task.get("budget", {}).get("used_image_calls", 0))
        if used >= allowance:
            raise BudgetError("已达到已授权的生图调用上限（%d 次）。请向用户说明并取得新的授权后再继续。" % allowance)
        plan_approval = latest_approval(root, product, "plan") or {}
        total_budget = plan_approval.get("authorized_total_cost_usd")
        if total_budget is not None:
            known = sum(float(item["cost"]) for item in requests(root, product)
                        if item.get("cost") is not None and item.get("kind") == "image")
            if known >= float(total_budget):
                raise BudgetError("已达到已授权的总费用上限（$%s）。未知费用仍需人工核对。" % total_budget)
        request_id = str(uuid.uuid4())
        items = requests(root, product)
        items.append({"request_id": request_id, "kind": kind, "stage": stage,
                      "image_task_id": image_task_id, "status": "pending",
                      "started_at": now(), "ended_at": None,
                      "meta": meta or {}, "usage": None, "cost": None})
        write_requests(root, product, items)
        task["budget"]["used_image_calls"] = used + 1
        if kind == "vision":
            task["counts"]["vision_calls"] = int(task.get("counts", {}).get("vision_calls", 0)) + 1
        save_task(root, product, task)
        return request_id


def finish_request(root, product, request_id, status, *, usage=None, cost=None, error=None):
    with lock(root, product):
        items = requests(root, product)
        for item in items:
            if item["request_id"] == request_id:
                item.update({"status": status, "ended_at": now(), "usage": usage, "cost": cost, "error": error})
                break
        write_requests(root, product, items)
        if status == "succeeded":
            task = load_task(root, product)
            task["counts"]["generated"] = int(task.get("counts", {}).get("generated", 0)) + (1 if items and any(i["request_id"] == request_id and i["kind"] == "image" for i in items) else 0)
            save_task(root, product, task)


def cost_summary(root, product):
    items = requests(root, product)
    known = sum(float(i["cost"]) for i in items if i.get("cost") is not None)
    unknown = sum(1 for i in items if i.get("cost") is None and i.get("status") in ("succeeded", "unknown"))
    return {"known_usd": round(known, 4) if known else None, "unknown_charge_requests": unknown,
            "image_calls": sum(1 for i in items if i["kind"] == "image" and i["status"] == "succeeded"),
            "vision_calls": sum(1 for i in items if i["kind"] == "vision" and i["status"] == "succeeded"),
            "pending": sum(1 for i in items if i["status"] == "pending"),
            "unknown": sum(1 for i in items if i["status"] == "unknown")}


# --- image helpers ---------------------------------------------------------

def probe_image(path):
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return {"width": image.width, "height": image.height, "format": image.format, "mode": image.mode}
    except Exception as exc:
        raise AgsError("无法读取图片 %s：%s" % (Path(path).name, exc))


def convert_working_copy(source, destination):
    """Convert to a vision-friendly PNG/JPEG without touching the source."""
    with Image.open(source) as image:
        image = image.convert("RGB")
        image.save(destination, format="PNG")
    return destination


def split_batches(items, size=6):
    items = list(items)
    return [items[i:i + size] for i in range(0, len(items), size)]


def contact_sheet(entries, output, columns=3, tile=360):
    """entries: list of (label, path). Missing files are skipped."""
    usable = [(label, path) for label, path in entries if Path(path).is_file()]
    if not usable:
        return None
    rows = (len(usable) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * (tile + 24) + 24, rows * (tile + 56) + 24), "#f4f1ea")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(canvas)
    for index, (label, path) in enumerate(usable):
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((tile, tile))
        x = 24 + (index % columns) * (tile + 24)
        y = 24 + (index // columns) * (tile + 56)
        canvas.paste(image, (x + (tile - image.width) // 2, y))
        draw.text((x + 6, y + tile + 14), str(label)[:48], fill="#1c2b26")
    canvas.save(output, quality=92)
    return output


def technical_check(path, task):
    issues = []
    try:
        info = probe_image(path)
    except AgsError as exc:
        return {"status": "technical_fail", "issues": [str(exc)], "dimensions": None}
    if min(info["width"], info["height"]) < 1000:
        issues.append("最短边低于 1000px（实际 %dx%d）" % (info["width"], info["height"]))
    ratio = task.get("aspect_ratio", "1:1")
    try:
        left, right = [float(part) for part in ratio.split(":")]
        expected = left / right
        actual = info["width"] / info["height"]
        if abs(actual - expected) / expected > 0.02:
            issues.append("实际比例 %.3f 与计划 %s 不符" % (actual, ratio))
    except (ValueError, ZeroDivisionError):
        issues.append("计划比例格式无效：%s" % ratio)
    if "MAIN" in task.get("usage", ""):
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            corners = [rgb.getpixel((0, 0)), rgb.getpixel((rgb.width - 1, 0)),
                       rgb.getpixel((0, rgb.height - 1)), rgb.getpixel((rgb.width - 1, rgb.height - 1))]
        if any(pixel != (255, 255, 255) for pixel in corners):
            issues.append("MAIN 候选图的四角不是纯白 #FFFFFF")
    return {"status": "technical_pass" if not issues else "technical_fail", "issues": issues, "dimensions": info}


def white_metrics(path):
    """Deterministic white-background signals; never a compliance verdict by itself."""
    info = probe_image(path)
    with Image.open(path) as source:
        image = source.convert("RGB")
        sample = image.copy()
        sample.thumbnail((1000, 1000))
        width, height = sample.size
        pixels = sample.load()
        border_total = border_white = border_pure = 0
        for x in range(width):
            for y in (0, height - 1):
                r, g, b = pixels[x, y]
                border_total += 1
                border_white += int(min(r, g, b) >= 245)
                border_pure += int((r, g, b) == (255, 255, 255))
        for y in range(height):
            for x in (0, width - 1):
                r, g, b = pixels[x, y]
                border_total += 1
                border_white += int(min(r, g, b) >= 245)
                border_pure += int((r, g, b) == (255, 255, 255))
        grayscale = sample.convert("L")
        mask = grayscale.point(lambda value: 255 if value < 245 else 0)
        bbox = mask.getbbox()
        coverage = 0.0
        if bbox:
            coverage = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / float(width * height)
        edges = grayscale.filter(ImageFilter.FIND_EDGES)
        stat = ImageStat.Stat(edges)
        sharpness = round(sum(stat.var) / len(stat.var), 2)
        corners = [image.getpixel((0, 0)), image.getpixel((image.width - 1, 0)),
                   image.getpixel((0, image.height - 1)), image.getpixel((image.width - 1, image.height - 1))]
    return {"width": info["width"], "height": info["height"], "format": info["format"],
            "border_white_ratio": round(border_white / float(border_total or 1), 4),
            "border_pure_white_ratio": round(border_pure / float(border_total or 1), 4),
            "corners_pure_white": all(pixel == (255, 255, 255) for pixel in corners),
            "product_coverage": round(coverage, 4), "sharpness": sharpness}


def combine_white_verdict(assessment, metrics):
    """Merge vision observations with deterministic checks into one honest label."""
    verdict = str(assessment.get("verdict") or "uncertain").lower()
    reasons = list(assessment.get("reasons") or [])
    hard, soft = [], []
    if min(metrics["width"], metrics["height"]) < 1000:
        hard.append("分辨率低于 1000px")
    if metrics["border_white_ratio"] < 0.90:
        hard.append("画面边缘大量非白，不能直接作为白底主图")
    if assessment.get("has_props"):
        hard.append("画面存在不属于商品的道具")
    if assessment.get("has_text"):
        hard.append("画面存在文字、水印或装饰")
    if assessment.get("product_complete") is False:
        hard.append("商品不完整或被裁切")
    if metrics.get("border_pure_white_ratio", metrics["border_white_ratio"]) < 0.995:
        soft.append("背景边缘不是纯白，可能需要修整")
    if metrics["product_coverage"] and not (0.15 <= metrics["product_coverage"] <= 0.98):
        soft.append("商品占画面比例可能不合理（约 %.0f%%）" % (metrics["product_coverage"] * 100))
    if metrics["width"] != metrics["height"]:
        soft.append("当前不是 1:1，若目标为正方形需要修整")
    reasons.extend(hard + soft)
    if verdict == "unusable" or hard:
        result = "unusable"
    elif verdict == "retouch" or soft:
        result = "retouch"
    elif verdict == "reuse":
        result = "reuse"
    else:
        result = "uncertain"
    return {"verdict": result, "reasons": reasons, "hard_issues": hard, "soft_issues": soft,
            "vision_verdict": verdict}


def build_prompt(product, task, *, use_copy=True, style_reference=False):
    facts = "；".join(product.get("visible_facts", [])[:12]) or "以参考图为准"
    lines = [
        "Create a photorealistic Amazon listing product image.",
        "Aspect ratio: %s. Target pixels: %s." % (task.get("aspect_ratio", "1:1"), task.get("pixel_target", "1024x1024")),
        "Product identity (must remain exact): %s." % facts,
        "Role: %s. Purpose: %s." % (task.get("usage", "Listing 副图"), task.get("purpose", "")),
        "Scene: %s" % task.get("scene", ""),
        "Composition: %s" % task.get("composition", ""),
        "Keep the product shape, proportions, colours, visible logos/print, closures and surface texture unchanged.",
        "Do not invent dimensions, materials, certifications, accessories, performance claims or additional products.",
    ]
    if "MAIN" in task.get("usage", ""):
        lines.append("Pure white RGB 255,255,255 background, product only, no props, no overlays, no text.")
    if use_copy:
        copy = task.get("copy", {}) or {}
        if copy.get("status") == "user_provided" and copy.get("text"):
            lines.append("Render this exact copy, spelled letter-for-letter: %s" % copy["text"])
        elif copy.get("status") == "approved_suggestion" and copy.get("text"):
            lines.append("Render this approved copy: %s" % copy["text"])
        else:
            lines.append("No text, labels, badges or watermarks.")
    else:
        lines.append("No text, labels, badges or watermarks.")
    if style_reference:
        lines.append("Use the supplied representative image only as a photography and layout style reference; its product colour must not override the original product references.")
    for constraint in task.get("constraints", []):
        lines.append("Constraint: %s" % constraint)
    return "\n".join(lines)


def representative_scores(images):
    """Explainable, deterministic score; higher means a better representative."""
    scored = []
    for task in images:
        score = 1
        text = " ".join([task.get("purpose", ""), task.get("scene", ""), task.get("composition", "")])
        if any(word in text for word in ("细节", "使用", "场景", "材质", "结构")):
            score += 3
        if task.get("copy", {}).get("text"):
            score += 1
        if "MAIN" in task.get("usage", ""):
            score -= 2
        if task.get("scene") and "白底" not in task.get("scene", ""):
            score += 1
        scored.append((score, task.get("display_number", 0), task))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored


def choose_representative(images):
    scored = representative_scores(images)
    if not scored:
        raise AgsError("套图方案中没有图片任务")
    return scored[0][2]


def versioned_path(directory, number, label, version, suffix=".png"):
    return Path(directory) / ("%02d_%s_v%02d%s" % (number, label, version, suffix))


def plan_cost_text(plan):
    quote = plan.get("cost_quote", {})
    status = quote.get("status", "unavailable")
    if status in ("verified", "estimated") and quote.get("amount_usd") is not None:
        label = "估算" if status == "estimated" else "依据报价"
        return "%s约 $%s（估算≠最终账单），最多 %d 次生图调用" % (label, quote["amount_usd"], quote.get("max_image_calls", 0))
    return "当前无法可靠预估实际费用；本次默认最多 %d 次生图调用" % quote.get("max_image_calls", 0)
