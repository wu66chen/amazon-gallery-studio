import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "execution_record.py"


class ExecutionRecordTest(unittest.TestCase):
    def test_writes_model_agnostic_redacted_record(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "record.json"
            subprocess.run([sys.executable, str(SCRIPT), "--output", str(output), "--stage", "识别", "--model", "gemini-3.5-flash", "--status", "通过", "--calls", "1", "--tokens", "1200"], check=True, capture_output=True)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(record["model"], "gemini-3.5-flash")
            self.assertEqual(record["status"], "通过")
            self.assertNotIn("Authorization", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
