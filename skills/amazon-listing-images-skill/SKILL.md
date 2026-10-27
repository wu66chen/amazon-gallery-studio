---
name: amazon-listing-images-skill
description: "Plan and create Amazon listing image sets from real product photos. Use for Amazon 商品套图、MAIN 首图、Listing 副图、多色商品图、场景图、细节图、白底主图复用. Imports source images, recognizes the product and existing white-background MAIN candidates with a vision model, proposes a configurable gallery plan with copy/white-background choices and costs, generates one representative image for approval, then completes, audits and delivers the remaining set with resumable records."
compatibility: "Requires Python 3.9+, requirements.txt, and network access to an OpenAI-compatible vision endpoint (chat/completions with images) and an OpenAI-compatible image edit endpoint (images/edits returning b64_json)."
metadata:
  version: "0.4.0"
  author: "wu66chen"
---

# Amazon Listing Images Skill

`<skill>` = the directory containing this `SKILL.md`; scripts are `<skill>/scripts/`. The **workspace** is the user's product project (current directory, `--workspace`, or `AMAZON_GALLERY_WORKSPACE`). Never write task files into `<skill>`.

Read [references/configuration.md](references/configuration.md) when configuring providers. Terms and approval semantics: [references/glossary.md](references/glossary.md); do not contradict it.

## Hard rules

- User-locked requirements (count, per-image purpose, ratio, pixels, usage, copy) win. Fill only unspecified fields.
- User source images are copied, never moved, overwritten or recompressed.
- Never invent materials, dimensions, certifications, performance, accessories or Amazon compliance.
- No paid image call without a persisted plan approval **and** remaining authorized calls. Do not hand-edit `confirmed`/approval JSON; use the CLIs.
- Representative is one Image Task chosen by the Agent, not necessarily 01. After approval it is not regenerated. Reused white-background tasks are never chosen as the paid representative.
- Automatic QA and white-background reuse checks are preliminary; only the user's explicit acceptance is approval. Never equate them with Amazon review.
- White-background reuse/retouch/generate/none is part of the plan; do not ask a separate white-background question round.

## 1. Import and recognize

```bash
python3 <skill>/scripts/import_assets.py --workspace "<workspace>" --source "<file-or-folder>" [--source ...]
```

- Validates real bytes, hashes, dedupes, stages outside the visible area, converts WEBP/TIFF to a working copy while keeping the original.
- Batch-recognizes **all** images (6 per request), builds `product-profile.json` with facts / inferences / unknowns / variants / reference hashes.
- Names the product from high-confidence vision results (never the source folder name), deduplicates as `产品名_02`, and creates the same product folder under all four categories.
- If vision cannot read pixels, it stops before planning high-fidelity images. Offer `--product` + `--offline` only for a clearly unverified neutral task.
- Record the vision calls in `api-requests.json`.

## 2. Plan

```bash
python3 <skill>/scripts/plan_gallery.py --workspace "<workspace>" --product "<产品名>" \
  [--count N] [--ratio 1:1] [--size 1024x1024] [--include-main] \
  [--copy-mode ask|none|provided|suggest] [--copy-text "..."] \
  [--white-bg ask|reuse|generate|none] [--price-per-image 0.00]   [--requirements plan-requirements.json]
```

When the user specifies per-image purposes, ratios, sizes or copy, write them into a `--requirements` JSON file (`{"count":N,"images":[{"number":3,"purpose":"...","ratio":"4:5","size":"1600x2000","copy":"..."}]}`) so they are locked in the plan instead of being re-invented.

- Defaults: Amazon Listing 副图 (MAIN only with `--include-main`), 1:1, 1024×1024, 6 images, Tokease `gemini-3.5-flash` + `gpt-image-2`.
- Builds per-image tasks (`img-01`…), reference IDs, copy state, scene, composition and ratio; freezes `plan_hash`.
- White background: `import_assets.py` evaluates all visible white-background candidates with deterministic metrics (resolution, border whiteness, coverage) plus the existing vision response. The plan recommends `reuse`, `retouch`, `generate` or `none`; reuse creates a MAIN task with `render: "reuse"` and no paid call. The plan brief shows a compact white module (`白A/白B/白C`) only when relevant; approving the whole plan confirms it. If the user already said "use existing / no white / only these 7 scenes", do not re-ask or silently replace a locked task.
- Picks the representative by explainable score from **paid** tasks only and stores `representative_task_id` (may be null when every task is reused).
- Cost quote is `unavailable` unless the user provides a verifiable per-image price. Reused images are excluded from the paid count. Never invent a dollar amount; the call-count ceiling protects the run.
- Write a **short plan brief in chat** (not only a file): product, count, ratio/pixels, per-image one-liners, representative choice, cost sentence, then:
  `1 按方案执行 / 2 修改指定编号 / 3 换风格`
- Ask copy mode once if unspecified (`1` user copy, `2` agent suggestions, `不要文案`). Ask white-background choice separately only when a white candidate exists: `沿用现有 / 生成新的 / 不需要白底`.
- User approval of the plan and cost is **one** decision; do not ask again before the representative unless the scope changes.

## 3. Record plan approval

After the user replies (e.g. `1`, `2`, `按方案执行`, `通过`), record it with the exact wording:

```bash
python3 <skill>/scripts/approve_plan.py --workspace "<workspace>" --product "<产品名>" \
  --user-expression "<用户的原始回复>" \
  --authorized-image-calls <本次最多生图调用数> \
  --quote-status unavailable|estimated|verified [--total-cost-usd X] \
  [--copy-choice none|provided|suggest] [--copy-text "..."] \
  [--white-choice reuse|generate|none] [--representative-task 03]
```

- Requires a user expression, a plan hash match and an explicit call allowance. It appends an approval event; it does not accept a bare boolean.
- If the user only wants changes, use `--decision change_requested` and replan.
- Changing the plan invalidates the previous approval hash.

## 4. Representative

Explain once, before the paid call: the representative's number/purpose, that it uses the user's API key and costs real money, the authorized range, and how to approve or modify. Then run:

```bash
python3 <skill>/scripts/generate_representative.py --workspace "<workspace>" --product "<产品名>" [--task N]
```

- Versions are `<NN>_<用途>_v01.png`, `_v02.png`; never overwrite.
- Technical check + vision QA against the original references. Save `代表图审核_v01.md` and `QA` JSON.
- Show the actual file, actual pixels, QA status and issues. Then:
  `1 通过，生成剩余图片 / 2 修改这张`.
- If the request result is unknown (timeout), the task becomes `blocked`; do not retry automatically.

## 5. Approve representative and continue

```bash
python3 <skill>/scripts/gallery_workflow.py --workspace "<workspace>" --product "<产品名>" \
  --image "<approved version file>" --approve --user-expression "<用户原话>" \
  [--authorized-image-calls <额外增加次数>] --execute
```

- Copies **that version** to `03_最终套图/<产品>/<NN>_<用途>.png`.
- `--execute` generates the remaining numbers in the same turn; never answer "已记录批准" and wait for another "继续".
- Only remaining numbers are generated; the approved representative is never regenerated.
- If the approved budget cannot cover the remaining set, say so before continuing and request additional authorization (recorded as `extra_cost`).

## 6. Batch, QA and partial delivery

`finish_gallery.py` (called by `--execute`) must:

- for `render: "reuse"`, copy the selected original into the pending candidates with technical checks/hash, never call a paid API, never overwrite the source, and mark it `source_reused`;
- for `render: "retouch"`, treat it as a paid retouch against the chosen candidate (pure white, product unchanged);
- use each generated task's own reference IDs plus the approved representative as a **style** reference (product facts stay from the originals);
- include the task's ratio and pixel target in the prompt and send the matching size;
- check the authorized call count before every paid call (hard stop);
- save candidates to `03_最终套图/<产品>/待审候选/`, run technical + vision QA per image, and write `质检_<NN>.json`;
- always produce `套图总览_待审.jpg` and `整套审核_待审.md` even when interrupted, incomplete or out of budget;
- mark states `gallery_pending_approval`, `partial` or `blocked`; never label unapproved work as passed;
- report counts separately: reused / retouched / generated, plus actual paid calls and unknown costs. Reuse must not consume authorized calls.

Resume: rerun the same command. Existing candidates with QA are skipped; never pay twice for a delivered number. `unknown` requests stop the run.

## 7. Final gallery approval

Show the overview, per-image status, issues, cost counts and remaining budget. Then:

- User says `通过` / `这套可以`:
  `python3 <skill>/scripts/finalize_gallery.py --workspace ... --product ... --approve --user-expression "<原话>"`
  This promotes candidates, writes `最终审核报告.md`, records the gallery approval, and sets `gallery_approved`.
- User asks to change specific numbers: `--request-change --number 04 --number 06`, then regenerate only those numbers.
- Incomplete set: refuse unless the user explicitly accepts partial delivery (`--accept-partial`).
- User says “开始下一套/下一个产品”: first finalize the current gallery with that wording, then start a new import.

## Stage briefs (numbers + wording)

Use short, stage-specific messages; not one fixed template. Always end with a concrete action.

- **T1 missing input** (rare): what was recognized, the single blocking question, recommended option.
- **T2 plan**: product / count / ratio / per-image table / white-background module (reuse, retouch, generate or none, with `白A/白B/白C` only when needed) / cost sentence / representative / `1 2 3` options.
- **T3 representative**: number, that it is a paid call, authorized range, `1 生成 / 2 先改方案`.
- **T4 representative review**: real preview, QA status + evidence, cost status, `1 通过并生成其余 / 2 修改`.
- **T5 gallery review**: completed X/N, overview, issues, counts by source (reused/retouched/generated), cost counts, `1 通过 / 2 改指定编号 / 3 看报告`.
- **T6 blocked/partial**: completed numbers, reason, preserved files, `1 检查后继续 / 2 查看已完成`.

Do not dump raw prompts, JSON ledgers or internal paths already shown. Store them in the product record folder.

## Configuration

Priority (low → high): built-in defaults → legacy `~/.config/amazon-gallery-studio/config.json` → new `~/.config/amazon-listing-images-skill/config.json` → legacy `<workspace>/.amazon-gallery-studio.json` → new `<workspace>/.amazon-listing-images-skill.json`. Legacy names are kept for existing users.
Keys: legacy user `.env` → new user `.env` → workspace `.env` → process environment. Both roles accept `base_url`, `model`, `api_key_env`. Remote endpoints must be HTTPS. Never print or persist keys.

## Failure rules

- Provider failure before a confirmed response: mark `unknown`, state `blocked`, no automatic paid retry.
- Definite failure with no charge: mark `failed`; retry only within the authorized count.
- Missing references or plan hash mismatch: stop and repair; do not generate from guesses.
- Never describe a plan, prompt or failed call as a completed image.
