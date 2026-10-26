import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ANALYSIS, WorkspaceCase, run  # noqa: E402


class ImportAndPlanTest(WorkspaceCase):
    def test_offline_import_creates_four_product_folders_and_preserves_source(self):
        output = self.import_product("中性商品")
        product = "中性商品"
        for category in ("01_原始素材", "02_代表图审批", "03_最终套图", "04_记录与报告"):
            self.assertTrue((self.root / "任务资产与审批" / category / product).is_dir(), category)
        original = self.root / "任务资产与审批/01_原始素材" / product / "R01_商品图.jpg"
        self.assertTrue(original.is_file())
        self.assertTrue((self.source / "商品图.jpg").is_file())
        profile = json.loads((self.root / "任务资产与审批/04_记录与报告" / product / "product-profile.json").read_text())
        self.assertEqual(profile["vision"]["status"], "unavailable")
        self.assertIn("未执行视觉识别", " ".join(profile["unknowns"]))
        self.assertIn("产品：", output)

    def test_saved_analysis_names_product_and_writes_profile(self):
        self.import_product(None, ANALYSIS)
        directory = self.root / "任务资产与审批/04_记录与报告/测试刷"
        profile = json.loads((directory / "product-profile.json").read_text())
        self.assertEqual(profile["product_name"], "测试刷")
        self.assertEqual(profile["visible_facts"][0], "圆形刷头")
        self.assertEqual(profile["vision"]["status"], "complete")
        task = json.loads((directory / "task.json").read_text())
        self.assertEqual(task["state"], "recognizing")

    def test_duplicate_product_names_get_suffix_in_all_four_folders(self):
        self.import_product(None, ANALYSIS)
        self.import_product(None, ANALYSIS)
        products = sorted(p.name for p in (self.root / "任务资产与审批/01_原始素材").iterdir())
        self.assertEqual(products, ["测试刷", "测试刷_02"])
        for category in ("02_代表图审批", "03_最终套图", "04_记录与报告"):
            self.assertTrue((self.root / "任务资产与审批" / category / "测试刷_02").is_dir())

    def test_plan_keeps_user_count_and_chooses_non_first_representative(self):
        self.import_product(None, ANALYSIS)
        self.plan("--count", "3", "--copy-mode", "none", "--white-bg", "none")
        directory = self.root / "任务资产与审批/04_记录与报告/测试刷"
        plan = json.loads((directory / "gallery-plan.json").read_text())
        self.assertEqual(len(plan["images"]), 3)
        self.assertEqual([t["display_number"] for t in plan["images"]], [1, 2, 3])
        self.assertNotEqual(plan["representative_task_id"], "img-01")
        representative = next(t for t in plan["images"] if t["id"] == plan["representative_task_id"])
        self.assertIn(representative["purpose"], ("使用场景", "可见细节"))
        brief = (directory / "方案简报.md").read_text()
        self.assertIn("代表图", brief)
        self.assertIn("无法可靠预估", brief)

    def test_user_aspect_and_size_are_locked(self):
        self.import_product(None, ANALYSIS)
        self.plan("--count", "2", "--ratio", "4:5", "--size", "1600x2000", "--copy-mode", "none")
        plan = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/gallery-plan.json").read_text())
        self.assertTrue(all(t["aspect_ratio"] == "4:5" for t in plan["images"]))
        self.assertTrue(all(t["pixel_target"] == "1600x2000" for t in plan["images"]))
        self.assertEqual(plan["requirements"]["aspect_ratio"]["source"], "user_locked")

    def test_requirements_file_locks_per_image_purpose_ratio_size_and_copy(self):
        self.import_product(None, ANALYSIS)
        requirements = self.base / "requirements.json"
        requirements.write_text(json.dumps({
            "count": 2,
            "images": [{"number": 2, "purpose": "包装展示", "usage": "Listing 副图",
                        "scene": "包装与商品同框", "composition": "包装完整可见",
                        "ratio": "4:5", "size": "1600x2000", "copy": "READY TO GIFT"}]}))
        self.plan("--requirements", requirements)
        plan = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/gallery-plan.json").read_text())
        second = plan["images"][1]
        self.assertEqual(second["purpose"], "包装展示")
        self.assertEqual(second["aspect_ratio"], "4:5")
        self.assertEqual(second["pixel_target"], "1600x2000")
        self.assertEqual(second["copy"], {"status": "user_provided", "text": "READY TO GIFT", "candidates": []})
        self.assertEqual(plan["requirements"]["copy_mode"]["value"], "provided")

    def test_task_assets_is_a_deprecated_compatibility_shim(self):
        result = run("task_assets.py", "--workspace", self.root, "--set-name", "旧接口", "--source", self.source,
                     env=self.env)
        self.assertIn("已弃用", result.stdout)
        self.assertTrue((self.root / "任务资产与审批/01_原始素材/旧接口").is_dir())


if __name__ == "__main__":
    unittest.main()
