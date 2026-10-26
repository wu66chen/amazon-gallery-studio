import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import WorkspaceCase  # noqa: E402
from PIL import Image  # noqa: E402

import import_assets  # noqa: E402


class ImportExtraTest(WorkspaceCase):
    def run_import(self, argv):
        with patch.object(sys, "argv", ["import_assets.py", *argv]), \
             patch.object(import_assets, "endpoint", side_effect=lambda role, root=None: {"key": "k", "base_url": "https://x/v1", "model": "fake"}):
            import_assets.main()

    def test_more_than_eight_images_are_recognized_in_batches(self):
        (self.source / "商品图.jpg").unlink()
        for index in range(9):
            Image.new("RGB", (1200, 1200), (index, index, index)).save(self.source / ("img%02d.png" % index))
        calls = []

        def vision(cfg, images, prompt, timeout=180):
            calls.append(len(images))
            return ({"product_name": "批量测试品", "visible_facts": ["事实%d" % len(calls)],
                     "inferences": [], "unknowns": [], "variants": [], "structural_features": [],
                     "white_background_candidates": []}, {"total_tokens": 5})

        with patch.object(import_assets, "vision_json", side_effect=vision):
            self.run_import(["--workspace", str(self.root), "--source", str(self.source)])
        self.assertEqual(calls, [6, 3])
        profile = json.loads((self.root / "任务资产与审批/04_记录与报告/批量测试品/product-profile.json").read_text())
        self.assertEqual(profile["vision"]["calls"], 2)
        self.assertIn("事实2", profile["visible_facts"])
        self.assertEqual(len(profile["references"]), 9)

    def test_webp_is_probed_converted_for_analysis_and_kept_as_source(self):
        webp = self.source / "图片.webp"
        Image.new("RGB", (1200, 1200), "white").save(webp, format="WEBP")
        self.run_import(["--workspace", str(self.root), "--source", str(webp), "--offline", "--product", "格式测试"])
        self.assertTrue(webp.is_file())
        profile = json.loads((self.root / "任务资产与审批/04_记录与报告/格式测试/product-profile.json").read_text())
        self.assertEqual(profile["references"][0]["conversion"], "converted")
        self.assertTrue((self.root / "任务资产与审批/01_原始素材/格式测试/R01_图片.webp").is_file())

    def test_identical_files_are_deduplicated_by_hash(self):
        duplicate = self.source / "副本.jpg"
        duplicate.write_bytes((self.source / "商品图.jpg").read_bytes())
        self.run_import(["--workspace", str(self.root), "--source", str(self.source), "--offline", "--product", "去重测试"])
        profile = json.loads((self.root / "任务资产与审批/04_记录与报告/去重测试/product-profile.json").read_text())
        self.assertEqual(len(profile["references"]), 1)


if __name__ == "__main__":
    unittest.main()
