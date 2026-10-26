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
from providers import ProviderError  # noqa: E402


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (1200, 1200), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class BatchTest(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.import_product(None, ANALYSIS)
        self.plan("--count", "3", "--copy-mode", "none", "--white-bg", "none")
        self.directory = self.root / "任务资产与审批/04_记录与报告/测试刷"
        self.final = self.root / "任务资产与审批/03_最终套图/测试刷"
        run("approve_plan.py", "--workspace", self.root, "--product", "测试刷",
            "--user-expression", "1", "--authorized-image-calls", "6",
            "--quote-status", "unavailable", "--copy-choice", "none", env=self.env)
        plan = json.loads((self.directory / "gallery-plan.json").read_text())
        self.representative = next(t for t in plan["images"] if t["id"] == plan["representative_task_id"])
        review = self.root / "任务资产与审批/02_代表图审批/测试刷"
        review.mkdir(parents=True, exist_ok=True)
        self.approved = review / ("%02d_使用场景_v01.png" % self.representative["display_number"])
        self.approved.write_bytes(image_bytes())
        run("gallery_workflow.py", "--workspace", self.root, "--product", "测试刷",
            "--image", self.approved, "--approve", "--user-expression", "通过", env=self.env)

    def run_batch(self, *, edit=None, vision=None, check=True):
        argv = ["finish_gallery.py", "--workspace", str(self.root), "--product", "测试刷"]
        edit = edit or (lambda *a, **k: (image_bytes(), {"total_tokens": 10}))
        vision = vision or (lambda *a, **k: ({"status": "pass", "issues": [], "summary": "统一"}, {}))
        with patch.object(sys, "argv", argv), \
             patch.object(finish_gallery, "edit_image", side_effect=edit), \
             patch.object(finish_gallery, "vision_json", side_effect=vision), \
             patch.object(finish_gallery, "endpoint", side_effect=lambda role, root=None: {"key": "k", "base_url": "https://x/v1", "model": role}):
            try:
                finish_gallery.main()
            except SystemExit:
                if check:
                    raise

    def test_batch_generates_only_remaining_numbers_and_is_idempotent(self):
        calls = []

        def edit(cfg, images, prompt, size, quality):
            calls.append(list(images))
            return image_bytes(), {"total_tokens": 10}

        self.run_batch(edit=edit)
        plan = json.loads((self.directory / "gallery-plan.json").read_text())
        self.assertEqual(len(calls), len(plan["images"]) - 1)
        candidates = list((self.final / "待审候选").glob("*.png"))
        self.assertEqual(len(candidates), len(plan["images"]) - 1)
        self.assertTrue((self.final / "套图总览_待审.jpg").is_file())
        self.assertTrue((self.final / "整套审核_待审.md").is_file())
        task = json.loads((self.directory / "task.json").read_text())
        self.assertEqual(task["state"], "gallery_pending_approval")
        # Representative was not regenerated, and each batch call carried source references plus the approved style image.
        self.assertEqual(len(calls[0]), 2)
        self.assertEqual(Path(calls[0][-1]).name, "%02d_使用场景.png" % self.representative["display_number"])
        before = len(calls)
        self.run_batch(edit=edit)
        self.assertEqual(len(calls), before)

    def test_budget_exhaustion_stops_with_partial_delivery(self):
        self.plan("--count", "4", "--copy-mode", "none", "--white-bg", "none")
        # Re-approve the new plan with only 2 calls: representative + one batch image.
        run("approve_plan.py", "--workspace", self.root, "--product", "测试刷",
            "--user-expression", "1", "--authorized-image-calls", "2",
            "--quote-status", "unavailable", "--copy-choice", "none", env=self.env)
        plan = json.loads((self.directory / "gallery-plan.json").read_text())
        rep = next(t for t in plan["images"] if t["id"] == plan["representative_task_id"])
        review = self.root / "任务资产与审批/02_代表图审批/测试刷"
        approved = review / ("%02d_使用场景_v01.png" % rep["display_number"])
        approved.write_bytes(image_bytes())
        run("gallery_workflow.py", "--workspace", self.root, "--product", "测试刷",
            "--image", approved, "--approve", "--user-expression", "通过", env=self.env)
        # Simulate the representative call already consumed one of the two authorized calls.
        ags_core.reserve_paid_call(self.root, "测试刷", kind="image", stage="representative")
        self.run_batch()
        task = json.loads((self.directory / "task.json").read_text())
        self.assertEqual(task["state"], "partial")
        self.assertTrue((self.final / "套图总览_待审.jpg").is_file())
        self.assertTrue((self.final / "整套审核_待审.md").is_file())
        self.assertEqual(len(list((self.final / "待审候选").glob("*.png"))), 1)

    def test_unknown_batch_failure_pauses_and_keeps_partial_assets(self):
        self.run_batch(edit=lambda *a, **k: (_ for _ in ()).throw(ProviderError("timeout")), check=False)
        ledger = json.loads((self.directory / "api-requests.json").read_text())
        self.assertEqual(ledger[-1]["status"], "unknown")
        task = json.loads((self.directory / "task.json").read_text())
        self.assertEqual(task["state"], "blocked")
        self.assertTrue((self.final / "整套审核_待审.md").is_file())

    def test_representative_approval_with_execute_continues_in_same_command(self):
        import gallery_workflow
        argv = ["gallery_workflow.py", "--workspace", str(self.root), "--product", "测试刷",
                "--image", str(self.approved), "--approve", "--user-expression", "通过", "--execute"]
        with patch.object(sys, "argv", argv), \
             patch.object(finish_gallery, "run", return_value={"status": "dry-run", "completed": 2,
                                                               "remaining": 0, "report": None}) as mocked:
            gallery_workflow.main()
        self.assertEqual(mocked.call_count, 1)

    def test_final_approval_promotes_candidates_and_records_user_expression(self):
        self.run_batch()
        run("finalize_gallery.py", "--workspace", self.root, "--product", "测试刷",
            "--approve", "--user-expression", "通过", env=self.env)
        plan = json.loads((self.directory / "gallery-plan.json").read_text())
        for task in plan["images"]:
            self.assertTrue((self.final / task["final_file"]).is_file(), task["final_file"])
        task = json.loads((self.directory / "task.json").read_text())
        self.assertEqual(task["state"], "gallery_approved")
        self.assertTrue((self.final / "最终审核报告.md").is_file())
        approval = ags_core.latest_approval(self.root, "测试刷", "gallery")
        self.assertEqual(approval["user_expression"], "通过")

    def test_finalize_refuses_incomplete_without_explicit_acceptance(self):
        self.run_batch(edit=lambda *a, **k: (_ for _ in ()).throw(ProviderError("timeout")), check=False)
        result = run("finalize_gallery.py", "--workspace", self.root, "--product", "测试刷",
                     "--approve", "--user-expression", "通过", env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--accept-partial", result.stderr)


if __name__ == "__main__":
    unittest.main()
