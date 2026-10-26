import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ANALYSIS, WorkspaceCase, run  # noqa: E402

from PIL import Image  # noqa: E402
import finish_gallery  # noqa: E402
import ags_core  # noqa: E402


def product_photo(path):
    image = Image.new("RGB", (1200, 1200), "white")
    draw = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(image)
    draw.rectangle((360, 240, 840, 980), fill=(120, 90, 60))
    image.save(path)


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (1200, 1200), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class WhiteReuseTest(WorkspaceCase):
    def test_reused_white_reference_is_copied_without_paid_generation(self):
        product_photo(self.source / "商品图.jpg")
        analysis = json.loads(json.dumps(ANALYSIS))
        analysis["analysis"]["white_background_candidates"] = [1]
        analysis["analysis"]["white_background_assessments"] = [{
            "reference_index": 1, "verdict": "reuse", "reasons": ["白底、无道具、商品完整"],
            "has_props": False, "has_text": False, "product_complete": True,
            "variant_label": "", "composition_note": "居中，留白合理"}]
        self.import_product(None, analysis)
        self.plan("--count", "2", "--include-main", "--copy-mode", "none", "--white-bg", "ask")
        run("approve_plan.py", "--workspace", self.root, "--product", "测试刷",
            "--user-expression", "1", "--authorized-image-calls", "4", "--quote-status", "unavailable",
            "--copy-choice", "none", "--white-choice", "reuse", env=self.env)
        directory = self.root / "任务资产与审批/04_记录与报告/测试刷"
        final = self.root / "任务资产与审批/03_最终套图/测试刷"
        plan = json.loads((directory / "gallery-plan.json").read_text())
        representative = next(t for t in plan["images"] if t["id"] == plan["representative_task_id"])
        review = self.root / "任务资产与审批/02_代表图审批/测试刷"
        rep_label = "".join(ch for ch in representative["purpose"] if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")[:24]
        approved = review / ("%02d_%s_v01.png" % (representative["display_number"], rep_label))
        approved.parent.mkdir(parents=True, exist_ok=True)
        approved.write_bytes(image_bytes())
        run("gallery_workflow.py", "--workspace", self.root, "--product", "测试刷",
            "--image", approved, "--approve", "--user-expression", "通过", env=self.env)
        calls = []

        def edit(cfg, images, prompt, size, quality):
            calls.append(1)
            return image_bytes(), None

        argv = ["finish_gallery.py", "--workspace", str(self.root), "--product", "测试刷"]
        with patch.object(sys, "argv", argv), \
             patch.object(finish_gallery, "edit_image", side_effect=edit), \
             patch.object(finish_gallery, "vision_json", return_value=({"status": "pass", "issues": [], "summary": "ok"}, {})), \
             patch.object(finish_gallery, "endpoint", side_effect=lambda role, root=None: {"key": "k", "base_url": "https://x/v1", "model": role}):
            finish_gallery.main()
        main_task = next(t for t in plan["images"] if "MAIN" in t["usage"])
        label = "".join(ch for ch in main_task["purpose"] if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")[:24]
        candidate = final / "待审候选" / ("%02d_%s.png" % (main_task["display_number"], label))
        self.assertTrue(candidate.is_file())
        self.assertNotEqual(representative["render"], "reuse")
        report = (final / "整套审核_待审.md").read_text()
        self.assertIn("复用 1", report)
        qa = json.loads((directory / ("质检_%02d.json" % main_task["display_number"])).read_text())
        self.assertEqual(qa["source"], "reused")
        self.assertTrue(qa["source_sha256"])
        # Only the non-MAIN task called the paid image endpoint.
        self.assertEqual(len(calls), 0)
        ledger_file = directory / "api-requests.json"
        ledger = json.loads(ledger_file.read_text()) if ledger_file.is_file() else []
        self.assertFalse(any(item.get("image_task_id") == main_task["id"] for item in ledger))
        # Re-running is idempotent: the reused candidate is not copied or charged twice.
        with patch.object(sys, "argv", argv), \
             patch.object(finish_gallery, "edit_image", side_effect=edit), \
             patch.object(finish_gallery, "vision_json", return_value=({"status": "pass", "issues": [], "summary": "ok"}, {})), \
             patch.object(finish_gallery, "endpoint", side_effect=lambda role, root=None: {"key": "k", "base_url": "https://x/v1", "model": role}):
            finish_gallery.main()
        self.assertEqual(len(calls), 0)
        self.assertEqual(len(list((final / "待审候选").glob("*.png"))), 1)
        run("finalize_gallery.py", "--workspace", self.root, "--product", "测试刷",
            "--approve", "--user-expression", "通过", env=self.env)
        final_plan = json.loads((directory / "gallery-plan.json").read_text())
        self.assertTrue((final / final_plan["images"][0]["final_file"]).is_file())
        self.assertIn("复用 1", (final / "最终审核报告.md").read_text())


class AllReuseTest(WorkspaceCase):
    def test_single_reused_main_needs_no_representative_or_paid_call(self):
        product_photo(self.source / "商品图.jpg")
        analysis = json.loads(json.dumps(ANALYSIS))
        analysis["analysis"]["white_background_candidates"] = [1]
        analysis["analysis"]["white_background_assessments"] = [{
            "reference_index": 1, "verdict": "reuse", "reasons": ["白底可用"],
            "has_props": False, "has_text": False, "product_complete": True,
            "variant_label": "", "composition_note": "居中"}]
        self.import_product(None, analysis)
        self.plan("--count", "1", "--copy-mode", "none")
        directory = self.root / "任务资产与审批/04_记录与报告/测试刷"
        plan = json.loads((directory / "gallery-plan.json").read_text())
        self.assertIsNone(plan["representative_task_id"])
        run("approve_plan.py", "--workspace", self.root, "--product", "测试刷",
            "--user-expression", "1", "--authorized-image-calls", "0",
            "--quote-status", "unavailable", "--copy-choice", "none", env=self.env)
        argv = ["finish_gallery.py", "--workspace", str(self.root), "--product", "测试刷"]
        with patch.object(sys, "argv", argv), \
             patch.object(finish_gallery, "vision_json", return_value=({"status": "pass", "issues": [], "summary": "ok"}, {})), \
             patch.object(finish_gallery, "endpoint", side_effect=lambda role, root=None: {"key": "k", "base_url": "https://x/v1", "model": role}), \
             patch.object(finish_gallery, "edit_image", side_effect=AssertionError("no paid call expected")):
            finish_gallery.main()
        final = self.root / "任务资产与审批/03_最终套图/测试刷"
        self.assertEqual(len(list((final / "待审候选").glob("*.png"))), 1)
        task = json.loads((directory / "task.json").read_text())
        self.assertEqual(task["state"], "gallery_pending_approval")
        ledger = directory / "api-requests.json"
        self.assertFalse(ledger.is_file())


if __name__ == "__main__":
    unittest.main()
