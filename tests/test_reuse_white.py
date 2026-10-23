import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from finish_gallery import white_reference


class ReuseWhiteTest(unittest.TestCase):
    def test_reuses_only_a_confirmed_candidate_for_main_placement(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "图.jpg"
            source.write_bytes(b"image")
            plan = {"white_background": {"mode": "reuse", "confirmed": True, "candidates": [1]}, "images": [{"path": str(source)}]}
            self.assertEqual(white_reference(plan, {"placement": "Listing 首图"}, Path(temp)), source)
            self.assertIsNone(white_reference(plan, {"placement": "Listing 副图"}, Path(temp)))


if __name__ == "__main__":
    unittest.main()
