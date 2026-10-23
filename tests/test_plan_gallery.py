import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "plan_gallery.py"


def png(path):
    def chunk(tag, payload):
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00" + b"\xff\0\0" * 2 + b"\x00" + b"\xff\0\0" * 2)) + chunk(b"IEND", b""))


class PlannerTest(unittest.TestCase):
    def test_offline_does_not_claim_visual_facts_and_respects_count_and_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "source.png"
            png(image)
            overrides = root / "roles.json"
            overrides.write_text(json.dumps({"2": {"placement": "站外广告", "purpose": "节日祝福", "composition": "礼物构图"}}), encoding="utf-8")
            out = root / "review"
            subprocess.run([sys.executable, str(SCRIPT), "--offline", "--images", str(image), "--output", str(out), "--count", "2", "--roles", str(overrides), "--product", "圣诞树"], check=True, capture_output=True)
            report = json.loads((out / "商品识别与方案_圣诞树.json").read_text(encoding="utf-8"))
            self.assertIsNone(report["analysis"])
            self.assertEqual(report["recognition_status"], "未完成（仅有文件信息）")
            self.assertEqual(report["images"][0]["pixels"], [2, 2])
            self.assertEqual(len(report["rows"]), 2)
            self.assertEqual(report["rows"][1]["purpose"], "节日祝福")
            plan = (out / "方案摘要_圣诞树.md").read_text(encoding="utf-8")
            self.assertIn("尚未通过视觉确认", plan)
            self.assertIn("| 02 | 站外广告 | 节日祝福 | 礼物构图 |", plan)


if __name__ == "__main__":
    unittest.main()
