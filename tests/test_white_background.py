import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_plan_gallery import png


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "plan_gallery.py"


class WhiteBackgroundTest(unittest.TestCase):
    def test_existing_white_background_requires_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "white.png"
            png(source)
            analysis = root / "analysis.json"
            analysis.write_text(json.dumps({"analysis": {"product_type": "刷子", "visible_facts": ["短柄"], "unknowns": [], "white_background_candidates": [1]}, "model": "gemini-3.5-flash"}, ensure_ascii=False))
            output = root / "report"
            subprocess.run([sys.executable, str(SCRIPT), "--analysis-json", str(analysis), "--images", str(source), "--product", "刷子", "--output", str(output)], capture_output=True, check=True)
            report = json.loads((output / "商品识别与方案_刷子.json").read_text())
            self.assertEqual(report["white_background"]["candidates"], [1])
            self.assertFalse(report["white_background"]["confirmed"])
            self.assertIn("是否还要生成新的白底图", (output / "方案摘要_刷子.md").read_text())


if __name__ == "__main__":
    unittest.main()
