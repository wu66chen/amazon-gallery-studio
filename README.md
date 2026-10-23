# Amazon Gallery Studio

面向电商运营的 Amazon 商品套图 Skill：先从真实商品照片识别可见事实，协助规划可配置张数的套图，再生成代表图并在获批后继续制作余图。

## 安装到 OpenCode 项目

把本仓库的 `skills/amazon-gallery-studio/SKILL.md` 放到目标项目的 `.opencode/skills/amazon-gallery-studio/SKILL.md`；把 `scripts/` 和 `requirements.txt` 放到目标项目根目录，运行 `python3 -m pip install -r requirements.txt`。重启 OpenCode 以加载项目 Skill。图片调用由项目自带脚本完成，不依赖本机 Codex 的图像脚本。

在目标项目根目录 `.env` 中设置 `TOKEASE_API_KEY`。此凭据同时供 Tokease `gemini-3.5-flash` 商品识别/质检与 `gpt-image-2` 生图使用；不要把 `.env` 提交到 Git。若通过 `--project` 指定项目，根目录须有 `.gallery-project-root` 标识，以防把外部素材目录误当项目。

## 运营流程

1. 用户给本地文件、外部文件夹路径或可读取的聊天附件；Agent 把商品原图复制到当前项目 `任务资产与审批/01_原始素材/<套图名称>/`。
2. Gemini 自动识图后，Agent 在对话中提供逐张方案、文案选项；如素材已有白底候选，询问沿用现有、生成新的或不纳入白底图。
3. 用户确认套图方案与预计费用后，Agent 调用 GPT Image 2 生成代表图，先进行 Gemini 自动初筛，再请用户审批。
4. 用户批准代表图后，同轮调用 `gallery_workflow.py --execute`。获批图与其余候选图片都归档到 `03_最终套图/<套图名称>/`，质检未通过的图片标为待复核，整套完成时生成总览与报告供最终审核。

## 边界

- 初始多模态识别会发起计费调用；生图须等待方案与预估费用确认。
- 多模态初筛不能替代人工确认商品细节与 Amazon 实际类目规则。
- `gpt-image-2` 接口可能返回与请求不相同的像素尺寸；交付时必须检查实际文件。
- 不从用户未提供的图片推断尺寸、材料、性能和包装内容。

在本仓库运行 `python3 -m unittest discover -s tests -v` 可验证非付费工作流；集成测试需自备 Tokease Key 与费用授权。
