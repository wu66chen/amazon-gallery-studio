import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
GLOSSARY = (ROOT / "docs/GLOSSARY.md").read_text(encoding="utf-8")
SKILL = (ROOT / "skills/amazon-gallery-studio/SKILL.md").read_text(encoding="utf-8")


class DocsTest(unittest.TestCase):
    def test_readme_has_short_glossary_and_sop(self):
        self.assertIn("## 常用术语", README)
        self.assertIn("## 核心能力", README)
        self.assertIn("员工套图生成 SOP", README)
        for term in ("套图（Gallery）", "逐图任务", "代表图", "MAIN", "人工终审", "任务工作区", "白底主图复用"):
            self.assertIn(term, README)
        self.assertIn("docs/GLOSSARY.md", README)
        self.assertTrue((ROOT / "docs/GLOSSARY.md").is_file())

    def test_sop_has_all_required_steps_and_boundaries(self):
        for step in ("提供产品图", "审阅方案", "白底处理", "确认方案并授权费用", "审阅代表图", "批量生成其余图片",
                     "审阅整套", "查看归档"):
            self.assertIn(step, README)
        self.assertIn("产生真实费用", README)
        self.assertIn("不代表 Amazon", README)
        self.assertIn("自动初审通过", README)
        self.assertIn("不会被覆盖", README)
        self.assertIn("失败或中断", README)

    def test_glossary_covers_terms_and_approval_boundaries(self):
        required = ("Gallery", "Image Task", "Representative", "Amazon MAIN", "Listing 副图",
                    "白底主图（White Background MAIN Image）", "原图复用", "修整", "新生成",
                    "自动初审", "人工终审", "方案确认", "生图费用授权", "生成调用上限",
                    "总预算", "任务工作区", "断点续跑", "部分交付", "状态机")
        for term in required:
            self.assertIn(term, GLOSSARY)
        self.assertIn("不代表", GLOSSARY)
        self.assertIn("不重复生成", GLOSSARY)
        self.assertIn("开始下一套", GLOSSARY)
        self.assertIn("gallery_approved", GLOSSARY)
        self.assertIn("复用不计入", GLOSSARY)

    def test_skill_and_glossary_share_state_vocabulary(self):
        for state in ("plan_pending_approval", "representative_approved", "gallery_pending_approval", "gallery_approved"):
            self.assertIn(state, GLOSSARY)
        for concept in ("representative", "authorized calls", "unknown", "partial"):
            self.assertIn(concept.lower(), SKILL.lower())
        self.assertIn("not regenerated", SKILL)

    def test_readme_links_and_commands_are_consistent(self):
        links = re.findall(r"\]\((?!https?://|#)([^)]+)\)", README)
        for link in links:
            self.assertTrue((ROOT / link).exists(), "missing link target: %s" % link)
        self.assertIn("npx skills add wu66chen/amazon-gallery-studio -g", README)
        self.assertIn("npx skills update -g", README)
        self.assertNotIn("npx skills check", README)
        self.assertEqual(README.count("```") % 2, 0)

    def test_no_secrets_or_absolute_private_paths_in_public_docs(self):
        text = README + GLOSSARY + SKILL
        self.assertIsNone(re.search(r"sk-[A-Za-z0-9]{16,}", text))
        self.assertNotRegex(text, r"/Users/[A-Za-z0-9._-]+/")

    def test_compatibility_is_explicit_about_unverified_agents(self):
        self.assertIn("未实测", README)
        self.assertIn("WorkBuddy", README)
        self.assertIn("未验证", README)


if __name__ == "__main__":
    unittest.main()
