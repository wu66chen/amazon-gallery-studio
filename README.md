# Ecommerce Visual Skills

**电商视觉创作技能集 · A collection of Agent Skills for ecommerce visual work**

一组可独立安装、可组合使用的 Agent Skills，面向电商运营、商品摄影、视觉设计与商业内容制作。通过支持 Agent Skills 的软件，让 AI Agent 完成商品视觉策划、图像生成与编辑、质量审核和素材交付。

推荐**用户级全局安装**：一次安装，即可在同一 Agent 的不同商品项目中调用；也可以只安装当前需要的某一个 Skill，不必安装整个合集。

遵循 [Agent Skills 开放规范](https://agentskills.io/specification)，兼容支持该规范与本地命令执行的 Agent。仓库保持 MIT License 开源。

## 核心优势

- **独立 Skill，按需安装**：每个 Skill 有自己的 `SKILL.md`、脚本、依赖和参考文档，可单独安装、单独更新。
- **真实商品保真**：以用户原始商品图为唯一外观依据，不编造材质、尺寸、认证或性能。
- **专业商业视觉流程**：先识图与规划，再确认方案与费用，先做代表图，再完成整套并审核。
- **可控付费调用**：方案审批、费用提示、授权调用次数与请求账本分离记录；不静默调用付费 API。
- **可追溯交付**：原始素材、代表图版本、最终成品、审核报告与费用记录按产品归档，支持断点续跑与部分交付。
- **普通用户友好**：对话中只展示当前需要看的方案、图片和选择；复杂 JSON 与内部日志留在任务记录中。

## 已提供的 Skills

| Skill | 中文名称 | 状态 | 说明 |
| --- | --- | --- | --- |
| [`amazon-listing-images-skill`](skills/amazon-listing-images-skill/README.md) | 亚马逊商品套图生成技能 | **可用** | 从真实商品图完成 Amazon Listing 套图规划、白底 MAIN 识别与复用、代表图审批、批量生成、视觉审核与交付。 |

每个 Skill 的安装、配置、员工 SOP 和术语说明，以该 Skill 自己的 README 为准。

## 快速开始（推荐全局安装）

### 1. 查看仓库内可安装的 Skills

```bash
npx skills add wu66chen/ecommerce-visual-skills --list
```

### 2. 只安装 Amazon Listing Images Skill

```bash
npx skills add wu66chen/ecommerce-visual-skills -g -s amazon-listing-images-skill
```

安装时按 Skills CLI 提示选择 Agent。`-g` 表示用户级全局安装；不加 `-g` 则只安装到当前项目。

### 3. 同时安装到多个 Agent

```bash
npx skills add wu66chen/ecommerce-visual-skills -g -a opencode codex claude-code cursor -s amazon-listing-images-skill
```

Agent 名称以你安装的 Skills CLI 支持列表为准。**不需要一次安装仓库中的全部 Skills**，未来新增 Skill 也不会影响已安装的 Skill。

### 4. 安装 Python 依赖

```bash
python3 -m pip install -r ~/.agents/skills/amazon-listing-images-skill/requirements.txt
```

若客户端安装到其他目录，请替换为实际的 `amazon-listing-images-skill` 路径。

### 5. 配置 API Key

推荐保存到用户级私有配置，而不是写进项目或仓库：

```bash
mkdir -p ~/.config/amazon-listing-images-skill
printf 'TOKEASE_API_KEY=你的密钥\n' > ~/.config/amazon-listing-images-skill/.env
chmod 600 ~/.config/amazon-listing-images-skill/.env
```

旧版 `~/.config/amazon-gallery-studio/.env` 继续兼容，无需重新配置。完整优先级见该 Skill 的 [配置说明](skills/amazon-listing-images-skill/references/configuration.md)。

## 技能选择与使用

1. 先在 [已提供的 Skills](#已提供的-skills) 中选择任务对应的 Skill。
2. 打开该 Skill 的 README，按其中的安装命令与 SOP 操作。
3. 在 Agent 所在商品项目中提供商品图，或给出可读取的本地路径。
4. 按 Skill 提示确认方案、费用、代表图与最终套图。

当前第一个 Skill 的完整使用说明：

- [Amazon Listing Images Skill README](skills/amazon-listing-images-skill/README.md)
- [完整术语与审批规则](docs/GLOSSARY.md)

## 多 Agent 兼容性

| Agent | 安装方式 | 验证状态 |
| --- | --- | --- |
| **OpenCode** | Skills CLI 全局安装；读取 `~/.agents/skills/` 等目录 | 已验证：本地/远程发现、全局安装、跨目录无付费流程 |
| **Codex** | Skills CLI 全局安装；使用其支持的技能目录 | 仅格式兼容，未实测 |
| **Claude Code** | Skills CLI 全局安装；用户级 `~/.claude/skills/` | 仅格式兼容，未实测 |
| **Cursor** | Skills CLI 安装；按 Cursor 当前版本技能目录 | 仅格式兼容，未实测 |
| **WorkBuddy** | 通过客户端“技能”界面导入完整 Skill 文件夹 | 未验证，请以实际版本界面为准 |

安装 Skill 不等于客户端自动获得读写本地文件、运行 Python 或调用 API 的权限；这些能力取决于具体 Agent 与配置。跨 Agent 的交互兜底始终是普通文字与 `1/2/3` 回复。

## 通用环境要求

- 支持 Agent Skills 且能执行本地命令的 Agent。
- 各 Skill 声明的 Python 版本与依赖（见对应 `requirements.txt`）。
- Node.js / `npx` 仅用于 Skills CLI 安装与更新。
- 可访问用户在 Skill 中配置的 OpenAI 兼容模型服务。
- 商品素材的格式要求以对应 Skill 说明为准。

## 更新与卸载

```bash
npx skills ls -g                      # 查看已安装的全局 Skills
npx skills update -g                  # 更新全局 Skills
npx skills remove -g amazon-listing-images-skill
```

只更新单个 Skill 不会覆盖其他 Skill。升级可能存在记录结构或脚本参数变化，建议先在测试用户试运行。

## 未来 Skill 规划

以下方向仍在规划中，**尚未实现，不可安装**。只有在实际开发、测试并满足独立安装规范后，才会加入 `skills/` 并提供正式安装说明。

| 规划中的 Skill | 计划职责 |
| --- | --- |
| `amazon-a-plus-design-skill` | Amazon A+ 内容策划、模块视觉设计、版式与可编辑交付。与 Listing 图片组明确区分。 |
| `product-color-material-skill` | 商品局部换色、材质替换、色卡还原、结构保真与颜色一致性审核。 |
| `ecommerce-image-qa-skill` | 对已有电商图片做独立视觉质量检查；不替代各生产 Skill 内部的自动质检。 |
| `ecommerce-campaign-visuals-skill` | 活动主视觉、促销横幅、独立站与社媒商业视觉。 |

新增 Skill 的判断标准：有独立用户任务、可单独安装、资源自包含、不与现有 Skill 重复、经验证后才列为可用。

## 常见问题

**必须安装整个仓库的 Skills 吗？** 不需要。使用 `-s <skill-id>` 只安装指定的 Skill。

**安装后找不到 Skill？** 检查安装目标 Agent、Skill 目录层级（`<skills>/<skill-id>/SKILL.md`）以及客户端是否重启或重新加载。

**可以只用某个 Skill 吗？** 可以。每个 Skill 的脚本、依赖和参考文档随其安装包一起分发。

**仓库以后会增加更多 Skill 吗？** 会，但只在真正完成并验证后加入；已安装的 Skill 不受影响。

**如何查看完整术语与审批边界？** 见 [docs/GLOSSARY.md](docs/GLOSSARY.md)，正式内容位于对应 Skill 的 `references/` 中。

## 开源许可证

本项目基于 [MIT License](LICENSE) 开源。

允许个人及商业使用、修改和再分发，但须保留原有版权及许可证声明。

## 相关链接

- [Agent Skills 规范](https://agentskills.io/specification)
- [Skills CLI](https://github.com/vercel-labs/skills)
- [OpenCode 技能文档](https://opencode.ai/docs/skills/)
- [Amazon Listing Images Skill](skills/amazon-listing-images-skill/README.md)
