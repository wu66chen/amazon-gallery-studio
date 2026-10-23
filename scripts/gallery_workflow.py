#!/usr/bin/env python3
"""Gallery approval and delivery state transitions; paid generation is opt-in."""

import argparse
import json
from pathlib import Path
import shutil

from api_runtime import PROJECT


def paths(set_name):
    if not set_name or set_name in (".", "..") or "/" in set_name or "\\" in set_name:
        raise ValueError("套图名称必须是一个文件夹名")
    root = PROJECT / "任务资产与审批"
    return (root / "01_原始素材" / set_name, root / "02_代表图审批" / set_name,
            root / "03_最终套图" / set_name, root / "04_记录与报告")


def approve(set_name, plan_file, representative):
    original, review, final, records = paths(set_name)
    plan_file = plan_file.resolve(strict=True)
    if plan_file.parent != records.resolve():
        raise ValueError("方案记录必须在当前项目的 04_记录与报告")
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    if not plan.get("confirmed") or not plan.get("copy", {}).get("confirmed") or not plan.get("white_background", {}).get("confirmed", False):
        raise ValueError("方案、文案和白底图选择尚未确认")
    if not plan.get("cost_estimate_approved"):
        raise ValueError("预估费用尚未获批准，不得归档代表图或继续付费生成")
    representative = representative.resolve(strict=True)
    if representative.parent != review.resolve():
        raise ValueError("代表图必须来自当前套图的审批目录")
    if not representative.is_file() or representative.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise ValueError("代表图不存在或格式不支持")
    final.mkdir(parents=True, exist_ok=True)
    target = final / ("01_已批准代表图" + representative.suffix.lower())
    if target.exists() and target.read_bytes() != representative.read_bytes():
        raise ValueError("最终目录中已有不同的代表图，先检查后再继续")
    if not target.exists():
        shutil.copy2(representative, target)
    plan["representative_approved"] = True
    plan["representative_file"] = str(target)
    plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan, target


def remaining_tasks(plan):
    return [row for row in plan["rows"] if row["number"] != 1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-name", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--representative", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="After approval, run remaining paid generation immediately (requires approved cost estimate)")
    args = parser.parse_args()
    try:
        plan, target = approve(args.set_name, args.plan, args.representative)
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))
    print("代表图已归档：%s" % target)
    remaining = remaining_tasks(plan)
    if args.execute and remaining:
        from finish_gallery import run
        outcome = run(plan, args.set_name, execute=True)
        print("剩余图片执行结果：%s；已生成 %d/%d 张" % (outcome["status"], len(outcome["results"]), len(remaining)))
    elif remaining:
        print("剩余 %d 张待生成；此命令未带 --execute，因此未发起付费调用。" % len(remaining))


if __name__ == "__main__":
    main()
