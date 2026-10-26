# 配置与工作区

本 Skill 的脚本只依赖 Python 标准库和 `requirements.txt` 中的两个包。模型与密钥通过配置解析，不写死在代码里。

## 三个目录

| 目录 | 作用 | 是否应提交到 Git |
| --- | --- | --- |
| Skill 安装目录 | `SKILL.md`、`scripts/`、`requirements.txt`、`references/` | 由 Skill 仓库管理 |
| 用户配置目录 | `~/.config/amazon-gallery-studio/`（可用 `XDG_CONFIG_HOME` 或 `AMAZON_GALLERY_CONFIG_DIR` 改） | 否 |
| 任务工作区 | 商品项目目录；所有输出在 `任务资产与审批/` 下 | 通常否 |

脚本拒绝把 Skill 安装目录当作工作区，因此不会把商品图或生成结果写进全局技能目录。

## 工作区选择顺序

1. `--workspace` 参数
2. 环境变量 `AMAZON_GALLERY_WORKSPACE`
3. 当前工作目录

显式指定的已存在目录必须包含 `.gallery-project-root` 标记；`import_assets.py` 会自动创建。这样可以避免把外部素材文件夹误当工作区。新目录（尚不存在）可由脚本创建并自动写入标记。

## 模型角色

配置只允许两个角色，避免把不同能力混用：

```json
{
  "vision": {
    "base_url": "https://tokease.com/v1",
    "model": "gemini-3.5-flash",
    "api_key_env": "TOKEASE_API_KEY"
  },
  "image": {
    "base_url": "https://tokease.com/v1",
    "model": "gpt-image-2",
    "api_key_env": "TOKEASE_API_KEY"
  }
}
```

- `vision`：商品参考图识别、生成结果对照初筛。端点必须兼容 OpenAI `chat/completions` 的多图输入。
- `image`：代表图与后续图片编辑。端点必须兼容 OpenAI `images/edits` 并返回 `b64_json`。
- 不传配置时使用上面的默认值，保持原有 Tokease 行为。

可以更换为中转站或厂商自带的 OpenAI 兼容端点。厂商是否真的兼容、是否支持多图编辑，需要实际调用验证；本 Skill 不保证任意服务都能工作。不要把非 OpenAI 兼容的原生接口直接填入。

## 配置优先级

**端点配置**（低 → 高）：

1. 内置默认值
2. `~/.config/amazon-gallery-studio/config.json`
3. `<workspace>/.amazon-gallery-studio.json`

**密钥**（低 → 高）：

1. `~/.config/amazon-gallery-studio/.env`
2. `<workspace>/.env`
3. 当前进程环境变量

工作区覆盖用户级，进程环境覆盖两者。`api_key_env` 指定读取哪个变量名，因此不同服务商可以使用各自命名的密钥。

一次性配置（推荐，跨项目复用）：

```bash
mkdir -p ~/.config/amazon-gallery-studio
printf 'TOKEASE_API_KEY=你的密钥\n' > ~/.config/amazon-gallery-studio/.env
chmod 600 ~/.config/amazon-gallery-studio/.env
```

项目专属配置：在当前工作区 `.env` 中写入同名变量，并确保 `.gitignore` 包含 `.env`。

## 安全

- 错误信息只显示变量名和配置文件位置，不显示密钥值。
- 记录文件不保存密钥或请求头。
- 远程 `base_url` 必须为 HTTPS；仅 `localhost` / `127.0.0.1` 允许 HTTP。
- `.env` 不应提交到任何仓库。
