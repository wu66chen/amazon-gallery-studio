import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ANALYSIS, WorkspaceCase, run  # noqa: E402

from PIL import Image  # noqa: E402
import ags_core  # noqa: E402
import generate_representative  # noqa: E402
from providers import ProviderError  # noqa: E402


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (1200, 1200), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class RepresentativeTest(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.import_product(None, ANALYSIS)
        self.plan("--count", "3", "--copy-mode", "none", "--white-bg", "none")
        self.directory = self.root / "任务资产与审批/04_记录与报告/测试刷"

    def approve(self, calls=6):
        run("approve_plan.py", "--workspace", self.root, "--product", "测试刷",
            "--user-expression", "1", "--authorized-image-calls", str(calls),
            "--quote-status", "unavailable", "--copy-choice", "none", env=self.env)

    def run_representative(self, *extra):
        argv = ["generate_representative.py", "--workspace", str(self.root), "--product", "测试刷", *extra]
        with patch.object(sys, "argv", argv), \
             patch.object(generate_representative, "edit_image", return_value=(image_bytes(), {"total_tokens": 10})), \
             patch.object(generate_representative, "vision_json", return_value=({"status": "pass", "issues": [], "strengths": ["颜色一致"], "summary": "匹配"}, {})), \
             patch.object(generate_representative, "endpoint", side_effect=lambda role, root=None: {"key": "k", "base_url": "https://x/v1", "model": role}):
            generate_representative.main()

    def test_generation_uses_approved_non_first_representative_and_records_qa(self):
        self.approve()
        plan = json.loads((self.directory / "gallery-plan.json").read_text())
        representative = next(t for t in plan["images"] if t["id"] == plan["representative_task_id"])
        self.assertNotEqual(representative["display_number"], 1)
        self.run_representative()
        review = self.root / "任务资产与审批/02_代表图审批/测试刷"
        files = list(review.glob("%02d_*_v01.png" % representative["display_number"]))
        self.assertEqual(len(files), 1, files)
        task = json.loads((self.directory / "task.json").read_text())
        self.assertEqual(task["state"], "representative_reviewed")
        self.assertEqual(task["budget"]["used_image_calls"], 1)
        qa = json.loads((self.directory / "代表图QA_v01.json").read_text())
        self.assertEqual(qa["visual"]["status"], "pass")
        ledger = json.loads((self.directory / "api-requests.json").read_text())
        self.assertEqual(ledger[-1]["status"], "succeeded")
        self.assertEqual(ledger[-1]["image_task_id"], representative["id"])

    def test_new_generation_creates_new_version_without_overwriting(self):
        self.approve()
        self.run_representative()
        self.run_representative()
        review = self.root / "任务资产与审批/02_代表图审批/测试刷"
        self.assertEqual(len(list(review.glob("*_v01.png"))), 1)
        self.assertEqual(len(list(review.glob("*_v02.png"))), 1)

    def test_generation_requires_plan_approval(self):
        result = run("generate_representative.py", "--workspace", self.root, "--product", "测试刷",
                     env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("尚未获得用户确认", result.stderr)

    def test_budget_blocks_generation(self):
        self.approve(calls=3)
        for _ in range(3):
            ags_core.reserve_paid_call(self.root, "测试刷", kind="image", stage="representative")
        with self.assertRaises(ags_core.BudgetError):
            ags_core.reserve_paid_call(self.root, "测试刷", kind="image", stage="representative")

    def test_unknown_provider_error_stops_and_marks_request_unknown(self):
        self.approve()
        argv = ["generate_representative.py", "--workspace", str(self.root), "--product", "测试刷"]
        with patch.object(sys, "argv", argv), \
             patch.object(generate_representative, "edit_image", side_effect=ProviderError("timeout after send")), \
             patch.object(generate_representative, "endpoint", side_effect=lambda role, root=None: {"key": "k", "base_url": "https://x/v1", "model": role}):
            with self.assertRaises(SystemExit):
                generate_representative.main()
        ledger = json.loads((self.directory / "api-requests.json").read_text())
        self.assertEqual(ledger[-1]["status"], "unknown")
        task = json.loads((self.directory / "task.json").read_text())
        self.assertEqual(task["state"], "blocked")


if __name__ == "__main__":
    unittest.main()
