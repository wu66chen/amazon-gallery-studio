import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gallery_workflow
import finish_gallery


class WorkflowTest(unittest.TestCase):
    def test_approval_promotes_only_approved_representative_then_unlocks_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = root / "任务资产与审批"
            records = task / "04_记录与报告"
            approval = task / "02_代表图审批" / "测试商品"
            records.mkdir(parents=True)
            approval.mkdir(parents=True)
            plan = records / "方案.json"
            plan.write_text(json.dumps({"confirmed": True, "cost_estimate_approved": True, "copy": {"confirmed": True}, "white_background": {"confirmed": True}, "rows": [{"number": 1}, {"number": 2}, {"number": 3}]}))
            representative = approval / "02_修正版.png"
            representative.write_bytes(b"accepted")
            with patch.object(gallery_workflow, "PROJECT", root):
                result, target = gallery_workflow.approve("测试商品", plan, representative)
                self.assertEqual(target.read_bytes(), b"accepted")
                self.assertEqual(representative.read_bytes(), b"accepted")
                self.assertEqual(len(gallery_workflow.remaining_tasks(result)), 2)

    def test_approval_rejects_unconfirmed_white_background(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = root / "任务资产与审批" / "04_记录与报告"
            approval = root / "任务资产与审批" / "02_代表图审批" / "测试商品"
            records.mkdir(parents=True)
            approval.mkdir(parents=True)
            plan = records / "方案.json"
            plan.write_text(json.dumps({"confirmed": True, "cost_estimate_approved": True, "copy": {"confirmed": True}, "white_background": {"confirmed": False}}))
            image = approval / "代表图.png"
            image.write_bytes(b"data")
            with patch.object(gallery_workflow, "PROJECT", root):
                with self.assertRaisesRegex(ValueError, "白底图选择"):
                    gallery_workflow.approve("测试商品", plan, image)

    def test_unapproved_gallery_cannot_start_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(gallery_workflow, "PROJECT", Path(temp)):
                with self.assertRaisesRegex(ValueError, "未获批准"):
                    finish_gallery.run({"rows": [{"number": 2}]}, "测试商品")

    def test_cost_rejection_does_not_promote_image_or_mutate_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = root / "任务资产与审批/04_记录与报告"
            review = root / "任务资产与审批/02_代表图审批/测试商品"
            records.mkdir(parents=True)
            review.mkdir(parents=True)
            plan = records / "方案.json"
            data = {"confirmed": True, "copy": {"confirmed": True}, "white_background": {"confirmed": True}}
            plan.write_text(json.dumps(data))
            image = review / "代表图.png"
            image.write_bytes(b"approved")
            with patch.object(gallery_workflow, "PROJECT", root):
                with self.assertRaisesRegex(ValueError, "预估费用"):
                    gallery_workflow.approve("测试商品", plan, image)
            self.assertEqual(json.loads(plan.read_text()), data)
            self.assertFalse((root / "任务资产与审批/03_最终套图/测试商品/01_已批准代表图.png").exists())

    def test_approved_gallery_dry_run_lists_remaining_without_paid_call(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            final = root / "任务资产与审批/03_最终套图/测试商品"
            original = root / "任务资产与审批/01_原始素材/测试商品"
            final.mkdir(parents=True)
            original.mkdir(parents=True)
            representative = final / "01_已批准代表图.png"
            representative.write_bytes(b"approved")
            (original / "原图.jpg").write_bytes(b"source")
            plan = {"representative_approved": True, "representative_file": str(representative),
                    "rows": [{"number": 1}, {"number": 2}, {"number": 3}]}
            with patch.object(gallery_workflow, "PROJECT", root):
                result = finish_gallery.run(plan, "测试商品")
            self.assertEqual(result["remaining"], 2)
            self.assertEqual(result["status"], "dry-run")

    def test_paid_batch_requires_approved_estimate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            final = root / "任务资产与审批/03_最终套图/测试商品"
            original = root / "任务资产与审批/01_原始素材/测试商品"
            final.mkdir(parents=True)
            original.mkdir(parents=True)
            representative = final / "01_已批准代表图.png"
            representative.write_bytes(b"approved")
            (original / "原图.jpg").write_bytes(b"source")
            plan = {"representative_approved": True, "representative_file": str(representative),
                    "rows": [{"number": 1}, {"number": 2}]}
            with patch.object(gallery_workflow, "PROJECT", root):
                with self.assertRaisesRegex(ValueError, "预估费用"):
                    finish_gallery.run(plan, "测试商品", execute=True)


if __name__ == "__main__":
    unittest.main()
