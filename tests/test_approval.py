import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ANALYSIS, WorkspaceCase, run  # noqa: E402
import ags_core  # noqa: E402


class ApprovalTest(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.import_product(None, ANALYSIS)
        self.plan("--count", "3", "--copy-mode", "ask", "--white-bg", "none")
        self.directory = self.root / "任务资产与审批/04_记录与报告/测试刷"

    def approve(self, *extra, user="1", calls="4", check=True):
        return run("approve_plan.py", "--workspace", self.root, "--product", "测试刷",
                   "--user-expression", user, "--authorized-image-calls", calls,
                   "--quote-status", "unavailable", *extra, env=self.env, check=check)

    def test_copy_choice_is_required_before_plan_approval(self):
        result = self.approve(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("文案方式", result.stderr)
        self.assertEqual(ags_core.approvals(self.root, "测试刷"), [])

    def test_approval_records_hash_and_authorization(self):
        self.approve("--copy-choice", "none")
        plan = json.loads((self.directory / "gallery-plan.json").read_text())
        approval = ags_core.latest_approval(self.root, "测试刷", "plan")
        self.assertEqual(approval["plan_hash"], plan["plan_hash"])
        self.assertEqual(approval["authorized_image_calls"], 4)
        self.assertEqual(approval["user_expression"], "1")
        task = json.loads((self.directory / "task.json").read_text())
        self.assertEqual(task["state"], "plan_approved")
        self.assertEqual(task["budget"]["authorized_image_calls"], 4)

    def test_zero_authorization_is_rejected(self):
        result = self.approve("--copy-choice", "none", calls="0", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("至少为 1", result.stderr)

    def test_unavailable_quote_rejects_dollar_amount(self):
        result = self.approve("--copy-choice", "none", "--total-cost-usd", "1.5", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("无法可靠估价", result.stderr)

    def test_plan_change_invalidates_approval_hash(self):
        self.approve("--copy-choice", "none")
        plan_path = self.directory / "gallery-plan.json"
        plan = json.loads(plan_path.read_text())
        plan["images"][0]["scene"] = "changed"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ags_core.AgsError, "哈希不一致"):
            ags_core.require_plan_approval(self.root, "测试刷")

    def test_change_request_is_recorded_without_approval(self):
        run("approve_plan.py", "--workspace", self.root, "--product", "测试刷",
            "--user-expression", "把 03 改成室内", "--decision", "change_requested", env=self.env)
        self.assertIsNone(ags_core.latest_approval(self.root, "测试刷", "plan"))
        events = ags_core.approvals(self.root, "测试刷")
        self.assertEqual(events[-1]["decision"], "change_requested")
        self.assertEqual(events[-1]["requested_change"], "把 03 改成室内")


if __name__ == "__main__":
    unittest.main()
