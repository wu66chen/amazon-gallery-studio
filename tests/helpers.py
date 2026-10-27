import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "amazon-listing-images-skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from PIL import Image  # noqa: E402

import ags_core  # noqa: E402
import api_runtime  # noqa: E402


def png(path, width=1200, height=1200, color="white"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), color).save(path)


def product_photo(path, size=(1200, 1200)):
    image = Image.new("RGB", size, "white")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    draw.rectangle((int(size[0] * 0.3), int(size[1] * 0.2), int(size[0] * 0.7), int(size[1] * 0.82)),
                   fill=(120, 90, 60))
    image.save(path)


def run(script, *args, env=None, check=True):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, check=check, env=env)


def base_env(temp):
    env = os.environ.copy()
    env["AMAZON_GALLERY_CONFIG_DIR"] = str(Path(temp) / "user-config")
    env["TOKEASE_API_KEY"] = "test-key-value"
    return env


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "workspace"
        self.env = base_env(self.temp.name)
        self.source = self.base / "source"
        png(self.source / "商品图.jpg")

    def tearDown(self):
        self.temp.cleanup()

    def import_product(self, name="测试刷", analysis=None):
        args = ["--workspace", self.root, "--source", self.source]
        if analysis is None:
            args += ["--offline", "--product", name]
        else:
            path = self.base / "analysis.json"
            path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            args += ["--analysis-json", path]
            if name:
                args += ["--product", name]
        result = run("import_assets.py", *args, env=self.env)
        return result.stdout

    def plan(self, *extra):
        run("plan_gallery.py", "--workspace", self.root, "--product", "测试刷", *extra, env=self.env)

    def approve(self, calls=6):
        run("approve_plan.py", "--workspace", self.root, "--product", "测试刷",
            "--user-expression", "1", "--authorized-image-calls", calls,
            "--quote-status", "unavailable", "--copy-choice", "none", env=self.env)


ANALYSIS = {"model": "fake-vision", "analysis": {
    "product_name": "测试刷", "product_group": "清洁工具", "confidence": "high",
    "visible_facts": ["圆形刷头", "短木柄", "浅黄色刷毛"],
    "inferences": [{"claim": "可能为木质手柄", "confidence": "low"}],
    "unknowns": ["材质种类", "精确尺寸"], "variants": [],
    "structural_features": ["圆头", "短柄"], "white_background_candidates": []}}
