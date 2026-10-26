import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/amazon-gallery-studio/scripts"))
from PIL import Image  # noqa: E402
import ags_core  # noqa: E402


def save(path, size=(1024, 1024), color="white"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


class QualityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_prompt_contains_ratio_pixel_copy_and_main_rules(self):
        product = {"visible_facts": ["圆形刷头", "短木柄"]}
        task = {"usage": "Amazon MAIN 首图", "purpose": "MAIN", "aspect_ratio": "1:1",
                "pixel_target": "1024x1024", "scene": "白底", "composition": "居中",
                "copy": {"status": "not_applicable", "text": ""}, "constraints": []}
        prompt = ags_core.build_prompt(product, task)
        self.assertIn("Aspect ratio: 1:1", prompt)
        self.assertIn("1024x1024", prompt)
        self.assertIn("Pure white", prompt)
        self.assertIn("No text", prompt)
        task["copy"] = {"status": "user_provided", "text": "EXACT COPY"}
        prompt = ags_core.build_prompt(product, task)
        self.assertIn("EXACT COPY", prompt)
        self.assertIn("spelled letter-for-letter", prompt)

    def test_technical_check_flags_low_resolution_wrong_ratio_and_main_corners(self):
        low = self.base / "low.png"
        save(low, (800, 800))
        result = ags_core.technical_check(low, {"usage": "Listing 副图", "aspect_ratio": "1:1"})
        self.assertEqual(result["status"], "technical_fail")
        self.assertTrue(any("1000px" in issue for issue in result["issues"]))
        offratio = self.base / "off.png"
        save(offratio, (1600, 1000))
        result = ags_core.technical_check(offratio, {"usage": "Listing 副图", "aspect_ratio": "1:1"})
        self.assertTrue(any("比例" in issue for issue in result["issues"]))
        colored = self.base / "main.png"
        save(colored, (1200, 1200), "grey")
        result = ags_core.technical_check(colored, {"usage": "Amazon MAIN 首图", "aspect_ratio": "1:1"})
        self.assertTrue(any("纯白" in issue for issue in result["issues"]))

    def test_contact_sheet_handles_missing_files(self):
        one = self.base / "1.png"
        save(one)
        out = self.base / "sheet.jpg"
        ags_core.contact_sheet([("01", one), ("02", self.base / "missing.png")], out)
        self.assertTrue(out.is_file())
        self.assertGreater(out.stat().st_size, 1000)

    def test_representative_scores_prefer_detail_over_main(self):
        images = [
            {"display_number": 1, "usage": "Amazon MAIN 首图", "purpose": "MAIN", "scene": "白底", "composition": ""},
            {"display_number": 2, "usage": "Listing 副图", "purpose": "可见细节", "scene": "近景", "composition": ""},
            {"display_number": 3, "usage": "Listing 副图", "purpose": "使用场景", "scene": "厨房", "composition": ""},
        ]
        chosen = ags_core.choose_representative(images)
        self.assertIn(chosen["display_number"], (2, 3))

    def test_plan_digest_ignores_runtime_progress_fields(self):
        plan = {"version": 1, "product": {}, "requirements": {}, "design": {}, "white_background": {},
                "cost_quote": {}, "representative_task_id": "img-01",
                "images": [{"id": "img-01", "status": "planned"}]}
        first = ags_core.plan_digest(plan)
        plan["images"][0]["status"] = "approved"
        plan["images"][0]["versions"] = [{"version": 1}]
        self.assertEqual(first, ags_core.plan_digest(plan))
        plan["images"][0]["scene"] = "changed"
        self.assertNotEqual(first, ags_core.plan_digest(plan))

    def test_versioned_path_is_stable(self):
        path = ags_core.versioned_path(self.base, 3, "细节", 2)
        self.assertEqual(path.name, "03_细节_v02.png")


if __name__ == "__main__":
    unittest.main()
