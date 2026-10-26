from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ANALYSIS, WorkspaceCase, run  # noqa: E402
import ags_core  # noqa: E402


class CostGuardTest(WorkspaceCase):
    def test_total_cost_limit_blocks_further_paid_calls(self):
        self.import_product(None, ANALYSIS)
        self.plan("--count", "3", "--copy-mode", "none", "--white-bg", "none")
        run("approve_plan.py", "--workspace", self.root, "--product", "测试刷",
            "--user-expression", "1", "--authorized-image-calls", "5",
            "--quote-status", "estimated", "--total-cost-usd", "0.01",
            "--copy-choice", "none", env=self.env)
        request = ags_core.reserve_paid_call(self.root, "测试刷", kind="image", stage="representative")
        ags_core.finish_request(self.root, "测试刷", request, "succeeded", cost=0.02)
        with self.assertRaises(ags_core.BudgetError):
            ags_core.reserve_paid_call(self.root, "测试刷", kind="image", stage="representative")


if __name__ == "__main__":
    unittest.main()
