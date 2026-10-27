import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
SKILL_README = (ROOT / "skills/amazon-listing-images-skill/README.md").read_text(encoding="utf-8")
GLOSSARY = (ROOT / "skills/amazon-listing-images-skill/references/glossary.md").read_text(encoding="utf-8")
GLOSSARY_ENTRY = (ROOT / "docs/GLOSSARY.md").read_text(encoding="utf-8")
SKILL = (ROOT / "skills/amazon-listing-images-skill/SKILL.md").read_text(encoding="utf-8")
LICENSE = (ROOT / "LICENSE").read_text(encoding="utf-8")


class DocsTest(unittest.TestCase):
    def test_root_readme_is_a_collection_homepage(self):
        self.assertTrue(README.startswith("# Ecommerce Visual Skills"))
        self.assertIn("电商视觉创作技能集", README)
        self.assertIn("amazon-listing-images-skill", README)
        self.assertIn("可用", README)
        self.assertIn("规划中", README)
        self.assertIn("amazon-a-plus-design-skill", README)
        self.assertIn("npx skills add wu66chen/ecommerce-visual-skills --list", README)
        self.assertIn("npx skills add wu66chen/ecommerce-visual-skills -g -s amazon-listing-images-skill", README)
        self.assertIn("skills/amazon-listing-images-skill/README.md", README)
        self.assertIn("[MIT License](LICENSE)", README)

    def test_skill_readme_keeps_terms_and_operator_sop(self):
        self.assertTrue(SKILL_README.startswith("# Amazon Listing Images Skill"))
        self.assertIn("## 常用术语", SKILL_README)
        self.assertIn("员工套图生成 SOP", SKILL_README)
        for step in ("提供产品图", "审阅方案", "白底处理", "确认方案并授权费用", "审阅代表图", "批量生成其余图片"):
            self.assertIn(step, SKILL_README)
        for term in ("套图（Gallery）", "逐图任务", "代表图", "MAIN", "人工终审", "任务工作区", "白底主图复用"):
            self.assertIn(term, SKILL_README)
        self.assertIn("产生真实费用", SKILL_README)
        self.assertIn("references/glossary.md", SKILL_README)
        self.assertIn("[MIT License](../../LICENSE)", SKILL_README)

    def test_glossary_entry_points_to_single_authoritative_copy(self):
        self.assertIn("../skills/amazon-listing-images-skill/references/glossary.md", GLOSSARY_ENTRY)
        required = ("Gallery", "Image Task", "Representative", "Amazon MAIN", "Listing 副图",
                    "白底主图（White Background MAIN Image）", "原图复用", "修整", "新生成",
                    "自动初审", "人工终审", "方案确认", "生图费用授权", "生成调用上限",
                    "总预算", "任务工作区", "断点续跑", "部分交付", "状态机")
        for term in required:
            self.assertIn(term, GLOSSARY)
        for state in ("plan_pending_approval", "representative_approved", "gallery_pending_approval", "gallery_approved"):
            self.assertIn(state, GLOSSARY)
        self.assertIn("复用不计入", GLOSSARY)
        self.assertIn("不重复生成", GLOSSARY)
        self.assertIn("开始下一套", GLOSSARY)

    def test_skill_frontmatter_matches_directory(self):
        self.assertIn("name: amazon-listing-images-skill", SKILL)
        self.assertIn("# Amazon Listing Images Skill", SKILL)
        self.assertIn("references/glossary.md", SKILL)
        for concept in ("white-background", "representative", "authorized calls", "unknown", "partial"):
            self.assertIn(concept.lower(), SKILL.lower())

    def test_public_links_are_valid_and_old_repo_name_is_gone(self):
        for text, base in ((README, ROOT), (SKILL_README, ROOT / "skills/amazon-listing-images-skill")):
            for link in re.findall(r"\]\((?!https?://|#)([^)]+)\)", text):
                self.assertTrue((base / link).exists(), "missing link target: %s (from %s)" % (link, base))
        public = README + SKILL_README + SKILL + GLOSSARY + GLOSSARY_ENTRY
        self.assertNotIn("wu66chen/amazon-gallery-studio", public)
        self.assertNotIn("skills/amazon-gallery-studio", public)
        self.assertEqual(README.count("```") % 2, 0)
        self.assertEqual(SKILL_README.count("```") % 2, 0)

    def test_no_secrets_or_private_absolute_paths(self):
        text = README + SKILL_README + GLOSSARY + SKILL
        self.assertIsNone(re.search(r"sk-[A-Za-z0-9]{16,}", text))
        self.assertNotRegex(text, r"/Users/[A-Za-z0-9._-]+/")

    def test_mit_license_is_preserved(self):
        self.assertIn("MIT License", LICENSE)
        self.assertIn("Copyright (c) 2026 Wesley Liu", LICENSE)
        self.assertIn("Permission is hereby granted", LICENSE)

    def test_compatibility_is_honest(self):
        self.assertIn("未实测", README)
        self.assertIn("WorkBuddy", README)
        self.assertIn("未验证", README)


if __name__ == "__main__":
    unittest.main()
