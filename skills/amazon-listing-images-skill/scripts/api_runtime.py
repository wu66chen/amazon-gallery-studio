#!/usr/bin/env python3
"""Resolve the task workspace, API endpoints and credentials for this skill.

Nothing here writes to the installed skill directory. Task files always live in
a user-selected workspace.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlparse


SKILL_DIR = Path(__file__).resolve().parents[1]
MARKER = ".gallery-project-root"
WORKSPACE_ENV = "AMAZON_GALLERY_WORKSPACE"
# New names for this skill; legacy names below remain supported for existing users.
CONFIG_NAME = ".amazon-listing-images-skill.json"
LEGACY_CONFIG_NAME = ".amazon-gallery-studio.json"
CONFIG_DIR_NAME = "amazon-listing-images-skill"
LEGACY_CONFIG_DIR_NAME = "amazon-gallery-studio"
FOLDERS = ("01_原始素材", "02_代表图审批", "03_最终套图", "04_记录与报告")
DEFAULT_ENDPOINTS = {
    "vision": {
        "base_url": "https://tokease.com/v1",
        "model": "gemini-3.5-flash",
        "api_key_env": "TOKEASE_API_KEY",
    },
    "image": {
        "base_url": "https://tokease.com/v1",
        "model": "gpt-image-2",
        "api_key_env": "TOKEASE_API_KEY",
    },
}
ROLES = tuple(DEFAULT_ENDPOINTS)


def user_config_dirs():
    """Preferred first; legacy second. Existing users keep their old config."""
    override = os.environ.get("AMAZON_GALLERY_CONFIG_DIR")
    if override:
        return [Path(override).expanduser()]
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return [root / CONFIG_DIR_NAME, root / LEGACY_CONFIG_DIR_NAME]


def user_config_dir():
    return user_config_dirs()[0]


def _inside(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def workspace(explicit=None):
    """Return the task workspace. Never the installed skill directory."""
    if explicit is not None:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
    elif os.environ.get(WORKSPACE_ENV):
        candidate = Path(os.environ[WORKSPACE_ENV]).expanduser()
    else:
        candidate = Path.cwd()
    candidate = candidate.resolve()
    if candidate == SKILL_DIR or _inside(candidate, SKILL_DIR):
        raise ValueError("任务工作区不能是 Skill 安装目录；请在商品项目目录中运行，或用 --workspace 指定工作区")
    if not candidate.exists():
        if explicit is None:
            raise ValueError("当前目录不存在：%s" % candidate)
        candidate.mkdir(parents=True)
        (candidate / MARKER).write_text("amazon-listing-images-skill\n", encoding="utf-8")
    if not candidate.is_dir():
        raise ValueError("任务工作区必须是目录：%s" % candidate)
    if explicit is not None and candidate != Path.cwd().resolve() and not (candidate / MARKER).is_file():
        raise ValueError(
            "指定的工作区缺少 %s：外部素材目录不能作为任务工作区。"
            "请在商品项目中运行，或先在该目录运行 import_assets.py。" % MARKER
        )
    return candidate


def initialise(explicit=None):
    """Create the workspace layout and its marker file."""
    root = workspace(explicit)
    (root / MARKER).write_text("amazon-listing-images-skill\n", encoding="utf-8")
    for folder in FOLDERS:
        (root / "任务资产与审批" / folder).mkdir(parents=True, exist_ok=True)
    return root


def _read_env_file(path):
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        if name.isidentifier():
            values[name] = value.strip().strip("\"'")
    return values


def credentials_env(root):
    """Legacy user .env, new user .env, workspace .env, then process environment."""
    values = {}
    for directory in reversed(user_config_dirs()):
        values.update(_read_env_file(directory / ".env"))
    values.update(_read_env_file(Path(root) / ".env"))
    values.update({name: value for name, value in os.environ.items() if value})
    return values


def _read_json(path):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("配置文件不是有效 JSON：%s（%s）" % (path, exc.msg))
    if not isinstance(data, dict):
        raise ValueError("配置文件必须是 JSON 对象：%s" % path)
    return data


def endpoint(role, root=None):
    """Resolve one API role without exposing its secret in errors or records."""
    if role not in ROLES:
        raise ValueError("未知 API 角色：%s（可用：%s）" % (role, ", ".join(ROLES)))
    root = workspace(root)
    values = credentials_env(root)
    selected = DEFAULT_ENDPOINTS[role]
    source = "内置默认值"
    config_candidates = []
    for directory in reversed(user_config_dirs()):
        config_candidates.append((_read_json(directory / "config.json"), str(directory / "config.json")))
    config_candidates.append((_read_json(root / LEGACY_CONFIG_NAME), str(root / LEGACY_CONFIG_NAME)))
    config_candidates.append((_read_json(root / CONFIG_NAME), str(root / CONFIG_NAME)))
    for candidate, label in config_candidates:
        if not candidate:
            continue
        unknown = set(candidate) - set(ROLES)
        if unknown:
            raise ValueError("未知配置角色：%s（只支持 vision、image）" % ", ".join(sorted(unknown)))
        if role in candidate:
            selected, source = candidate[role], label
    if not isinstance(selected, dict) or set(selected) != {"base_url", "model", "api_key_env"}:
        raise ValueError("%s 的配置必须且只能包含 base_url、model、api_key_env（来源：%s）" % (role, source))
    if not all(isinstance(selected[key], str) and selected[key].strip() for key in selected):
        raise ValueError("%s 的配置字段不能为空（来源：%s）" % (role, source))
    url = selected["base_url"].strip().rstrip("/")
    parsed = urlparse(url)
    local = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")
    if parsed.scheme != "https" and not local:
        raise ValueError("%s 的 base_url 必须使用 HTTPS（本机服务可用 HTTP）：%s" % (role, url))
    env_name = selected["api_key_env"].strip()
    if not env_name.isidentifier():
        raise ValueError("%s 的 api_key_env 不是有效的环境变量名" % role)
    key = values.get(env_name, "").strip()
    if not key:
        raise ValueError(
            "缺少 %s 凭据 %s。请任选一种方式配置：\n"
            "  1. 当前终端 export %s=...\n"
            "  2. 当前工作区 %s\n"
            "  3. 用户级 %s 或旧版兼容目录 %s（对所有项目生效）"
            % (role, env_name, env_name, root / ".env", user_config_dirs()[0] / ".env",
               user_config_dirs()[-1] / ".env")
        )
    return {"base_url": url, "model": selected["model"], "key": key, "api_key_env": env_name}


def redact(value):
    text = str(value)
    for name, secret in credentials_env(Path.cwd()).items():
        if secret and len(secret) >= 8 and ("KEY" in name.upper() or "TOKEN" in name.upper()):
            text = text.replace(secret, "<REDACTED>")
    return text
