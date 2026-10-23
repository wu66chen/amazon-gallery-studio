from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "task_assets.py"


class TaskAssetsTest(unittest.TestCase):
    def test_creates_folders_and_does_not_overwrite_user_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".gallery-project-root").write_text("test")
            source_dir = root / "outside"
            source_dir.mkdir()
            source = source_dir / "用户原名.jpg"
            source.write_bytes(b"original")
            subprocess.run([sys.executable, str(SCRIPT), "--project", str(root), "--set-name", "测试商品", "--source", str(source)], check=True, capture_output=True)
            task = root / "任务资产与审批"
            self.assertEqual(source.read_bytes(), b"original")
            self.assertTrue((task / "01_原始素材/测试商品/用户原名.jpg").is_file())
            self.assertTrue((task / "02_代表图审批/测试商品").is_dir())
            self.assertTrue((task / "03_最终套图/测试商品").is_dir())
            self.assertTrue((task / "04_记录与报告").is_dir())
            self.assertTrue((task / "README.md").is_file())

    def test_external_folder_imports_images_without_touching_unrelated_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".gallery-project-root").write_text("test")
            external = root / "百货测试"
            external.mkdir()
            (external / "产品 (1).jpg").write_bytes(b"first")
            (external / "产品 (2).png").write_bytes(b"second")
            (external / "说明.txt").write_text("leave me")
            subprocess.run([sys.executable, str(SCRIPT), "--project", str(root), "--set-name", "新品", "--source", str(external)], check=True, capture_output=True)
            dest = root / "任务资产与审批" / "01_原始素材" / "新品"
            self.assertEqual(sorted(p.name for p in dest.iterdir()), ["产品 (1).jpg", "产品 (2).png"])
            self.assertTrue((external / "产品 (1).jpg").exists())
            self.assertTrue((external / "说明.txt").exists())

    def test_existing_user_file_is_not_overwritten_on_name_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".gallery-project-root").write_text("test")
            dest = root / "任务资产与审批" / "01_原始素材" / "新品"
            dest.mkdir(parents=True)
            (dest / "同名.jpg").write_bytes(b"user file")
            external = root / "outside"
            external.mkdir()
            (external / "同名.jpg").write_bytes(b"different")
            subprocess.run([sys.executable, str(SCRIPT), "--project", str(root), "--set-name", "新品", "--source", str(external)], check=True, capture_output=True)
            self.assertEqual((dest / "同名.jpg").read_bytes(), b"user file")
            self.assertEqual(len(list(dest.glob("同名*.jpg"))), 2)


if __name__ == "__main__":
    unittest.main()
