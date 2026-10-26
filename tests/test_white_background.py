import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ANALYSIS, WorkspaceCase, product_photo, run  # noqa: E402
import ags_core  # noqa: E402


def analysis_with(verdict="reuse", **extra):
    data = json.loads(json.dumps(ANALYSIS))
    assessment = {"reference_index": 1, "verdict": verdict,
                  "reasons": ["测试评估"], "has_props": False, "has_text": False,
                  "product_complete": True, "variant_label": extra.pop("variant_label", ""),
                  "composition_note": "居中"}
    assessment.update(extra)
    data["analysis"]["white_background_candidates"] = [1]
    data["analysis"]["white_background_assessments"] = [assessment]
    return data


class WhiteDetectionTest(WorkspaceCase):
    def import_white(self, verdict="reuse", **extra):
        product_photo(self.source / "商品图.jpg")
        self.import_product(None, analysis_with(verdict, **extra))
        return json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/product-profile.json").read_text())

    def test_profile_records_metrics_and_reuse_verdict(self):
        profile = self.import_white()
        candidate = profile["white_background"]["candidates"][0]
        self.assertEqual(profile["white_background"]["status"], "reusable")
        self.assertEqual(candidate["verdict"], "reuse")
        self.assertGreater(candidate["technical"]["border_white_ratio"], 0.98)
        self.assertGreater(candidate["technical"]["product_coverage"], 0.1)
        self.assertTrue(candidate["technical"]["width"] >= 1000)

    def test_props_or_text_make_candidate_unusable(self):
        profile = self.import_white("reuse", has_props=True)
        self.assertEqual(profile["white_background"]["status"], "unusable")
        self.assertEqual(profile["white_background"]["candidates"][0]["verdict"], "unusable")

    def test_slightly_off_white_border_becomes_retouch(self):
        from PIL import Image
        image = Image.new("RGB", (1200, 1200), (248, 248, 248))
        from PIL import ImageDraw
        ImageDraw.Draw(image).rectangle((360, 240, 840, 980), fill=(120, 90, 60))
        image.save(self.source / "商品图.jpg")
        self.import_product(None, analysis_with("reuse"))
        profile = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/product-profile.json").read_text())
        self.assertEqual(profile["white_background"]["candidates"][0]["verdict"], "retouch")

    def test_missing_vision_assessment_falls_back_to_uncertain(self):
        product_photo(self.source / "商品图.jpg")
        data = json.loads(json.dumps(ANALYSIS))
        data["analysis"]["white_background_candidates"] = [1]
        self.import_product(None, data)
        profile = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/product-profile.json").read_text())
        self.assertIn(profile["white_background"]["candidates"][0]["verdict"], ("uncertain", "retouch"))


class WhitePlanTest(WhiteDetectionTest):
    def test_auto_reuse_includes_main_and_counts_paid_images_only(self):
        self.import_white()
        self.plan("--count", "6", "--copy-mode", "none")
        plan = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/gallery-plan.json").read_text())
        main = plan["images"][0]
        self.assertEqual(main["usage"], "Amazon MAIN 首图")
        self.assertEqual(main["render"], "reuse")
        self.assertEqual(main["reuse_reference"], "R01")
        self.assertEqual(plan["counts"], {"total": 6, "reused": 1, "retouch": 0,
                                          "generated": 5, "paid": 5})
        self.assertEqual(plan["cost_quote"]["max_image_calls"], 10)
        representative = next(t for t in plan["images"] if t["id"] == plan["representative_task_id"])
        self.assertNotEqual(representative["render"], "reuse")
        brief = (self.root / "任务资产与审批/04_记录与报告/测试刷/方案简报.md").read_text()
        self.assertIn("发现 1 张可复用候选", brief)
        self.assertIn("复用 1 张", brief)

    def test_no_white_choice_never_injects_main_or_asks(self):
        self.import_white()
        self.plan("--count", "4", "--copy-mode", "none", "--white-bg", "none")
        plan = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/gallery-plan.json").read_text())
        self.assertFalse(any("MAIN" in t["usage"] for t in plan["images"]))
        self.assertEqual(plan["counts"]["reused"], 0)
        brief = (self.root / "任务资产与审批/04_记录与报告/测试刷/方案简报.md").read_text()
        self.assertIn("本次不纳入", brief)

    def test_no_candidate_with_include_main_recommends_generation(self):
        product_photo(self.source / "商品图.jpg")
        data = json.loads(json.dumps(ANALYSIS))
        data["analysis"]["white_background_candidates"] = []
        data["analysis"]["white_background_assessments"] = []
        self.import_product(None, data)
        self.plan("--count", "3", "--copy-mode", "none", "--include-main")
        plan = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/gallery-plan.json").read_text())
        main = plan["images"][0]
        self.assertEqual(main["usage"], "Amazon MAIN 首图")
        self.assertEqual(main["render"], "generate")
        self.assertEqual(plan["white_background"]["recommendation"], "generate")
        brief = (self.root / "任务资产与审批/04_记录与报告/测试刷/方案简报.md").read_text()
        self.assertIn("未发现可直接复用的合格图", brief)

    def test_retouch_candidate_recommends_paid_retouch(self):
        self.import_white("retouch")
        self.plan("--count", "3", "--copy-mode", "none", "--include-main")
        plan = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/gallery-plan.json").read_text())
        main = plan["images"][0]
        self.assertEqual(main["render"], "retouch")
        self.assertEqual(plan["counts"]["retouch"], 1)
        self.assertEqual(plan["counts"]["paid"], 3)
        self.assertIn("修整", (self.root / "任务资产与审批/04_记录与报告/测试刷/方案简报.md").read_text())

    def test_explicit_scene_list_is_not_rewritten_with_reused_main(self):
        self.import_white()
        requirements = self.base / "requirements.json"
        requirements.write_text(json.dumps({
            "count": 7,
            "images": [{"number": i, "usage": "Listing 副图", "purpose": "场景 %d" % i} for i in range(1, 8)]
        }))
        self.plan("--requirements", requirements, "--copy-mode", "none")
        plan = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/gallery-plan.json").read_text())
        self.assertEqual(len(plan["images"]), 7)
        self.assertFalse(any("MAIN" in t["usage"] for t in plan["images"]))
        self.assertEqual(plan["counts"]["reused"], 0)
        self.assertTrue(all(t["purpose"].startswith("场景") for t in plan["images"]))

    def test_seven_total_with_one_reuse_keeps_seven_and_six_paid(self):
        self.import_white()
        self.plan("--count", "7", "--copy-mode", "none")
        plan = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/gallery-plan.json").read_text())
        self.assertEqual(plan["counts"]["total"], 7)
        self.assertEqual(plan["counts"]["reused"], 1)
        self.assertEqual(plan["counts"]["paid"], 6)
        self.assertEqual(sum(1 for t in plan["images"] if t["render"] != "reuse"), 6)

    def test_multicolour_without_variant_label_is_not_auto_reused(self):
        data = analysis_with("reuse")
        data["analysis"]["variants"] = [
            {"label": "深蓝", "colour": "深蓝", "evidence": "", "reference_index": 1},
            {"label": "紫色", "colour": "紫色", "evidence": "", "reference_index": 2},
        ]
        product_photo(self.source / "商品图.jpg")
        self.import_product(None, data)
        self.plan("--count", "3", "--copy-mode", "none", "--include-main")
        plan = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/gallery-plan.json").read_text())
        main = plan["images"][0]
        self.assertEqual(main["render"], "generate")
        self.assertEqual(plan["counts"]["reused"], 0)

    def test_candidate_with_wrong_ratio_is_retouch_not_direct_reuse(self):
        self.import_white()
        self.plan("--count", "2", "--ratio", "4:5", "--size", "1200x1500",
                  "--copy-mode", "none", "--include-main")
        plan = json.loads((self.root / "任务资产与审批/04_记录与报告/测试刷/gallery-plan.json").read_text())
        main = plan["images"][0]
        self.assertEqual(main["render"], "retouch")
        self.assertEqual(plan["counts"]["reused"], 0)
        self.assertIn("比例", plan["white_background"]["reason"])

    def test_explicit_reuse_without_candidate_is_rejected(self):
        product_photo(self.source / "商品图.jpg")
        data = json.loads(json.dumps(ANALYSIS))
        data["analysis"]["white_background_candidates"] = []
        data["analysis"]["white_background_assessments"] = []
        self.import_product(None, data)
        result = run("plan_gallery.py", "--workspace", self.root, "--product", "测试刷",
                     "--count", "3", "--copy-mode", "none", "--white-bg", "reuse",
                     env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("没有通过检查的可复用候选", result.stderr)

    def test_white_choice_none_at_approval_removes_main_and_rebinds_hash(self):
        self.import_white()
        self.plan("--count", "4", "--copy-mode", "none")
        directory = self.root / "任务资产与审批/04_记录与报告/测试刷"
        old = json.loads((directory / "gallery-plan.json").read_text())
        run("approve_plan.py", "--workspace", self.root, "--product", "测试刷",
            "--user-expression", "白C，不要白底", "--authorized-image-calls", "3",
            "--quote-status", "unavailable", "--copy-choice", "none", "--white-choice", "none",
            env=self.env)
        plan = json.loads((directory / "gallery-plan.json").read_text())
        self.assertFalse(any("MAIN" in t["usage"] for t in plan["images"]))
        self.assertEqual(plan["counts"]["total"], 3)
        self.assertEqual(plan["counts"]["reused"], 0)
        self.assertNotEqual(plan["plan_hash"], old["plan_hash"])
        approval = ags_core.latest_approval(self.root, "测试刷", "plan")
        self.assertEqual(approval["plan_hash"], plan["plan_hash"])
        self.assertEqual(approval["white_background_choice"], "none")


class WhiteTechnicalTest(unittest.TestCase):
    def test_combine_verdict_is_conservative(self):
        metrics = {"width": 1200, "height": 1200, "border_white_ratio": 1.0,
                   "product_coverage": 0.3, "corners_pure_white": True, "sharpness": 10}
        self.assertEqual(ags_core.combine_white_verdict({"verdict": "reuse"}, metrics)["verdict"], "reuse")
        self.assertEqual(ags_core.combine_white_verdict({"verdict": "reuse", "has_props": True}, metrics)["verdict"], "unusable")
        low = dict(metrics, width=600, height=600)
        self.assertEqual(ags_core.combine_white_verdict({"verdict": "reuse"}, low)["verdict"], "unusable")
        soft = dict(metrics, border_white_ratio=0.97)
        self.assertEqual(ags_core.combine_white_verdict({"verdict": "reuse"}, soft)["verdict"], "retouch")
        self.assertEqual(ags_core.combine_white_verdict({}, metrics)["verdict"], "uncertain")


if __name__ == "__main__":
    unittest.main()
