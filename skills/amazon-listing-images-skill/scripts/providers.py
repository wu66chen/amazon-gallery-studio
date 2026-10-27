#!/usr/bin/env python3
"""Thin provider adapters: OpenAI-compatible vision chat and image edits."""

import base64
import json
from pathlib import Path
import urllib.error
import urllib.request

from ags_core import AgsError


class ProviderError(AgsError):
    """The configured provider could not complete the request."""


def _encode(path):
    path = Path(path)
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode("ascii"))


def parse_json_answer(answer):
    if isinstance(answer, list):
        answer = "".join(part.get("text", "") for part in answer if isinstance(part, dict))
    text = str(answer).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError("视觉模型返回的不是可解析 JSON：%s" % exc.msg)
    if not isinstance(data, dict):
        raise ProviderError("视觉模型返回的 JSON 顶层不是对象")
    return data


def vision_json(cfg, images, prompt, timeout=180):
    content = [{"type": "text", "text": prompt}]
    for index, image in enumerate(images, 1):
        content.append({"type": "text", "text": "Reference image %d" % index})
        content.append({"type": "image_url", "image_url": {"url": _encode(image)}})
    body = json.dumps({"model": cfg["model"], "messages": [{"role": "user", "content": content}],
                       "temperature": 0}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=body,
                                     headers={"Authorization": "Bearer " + cfg["key"],
                                              "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ProviderError("视觉接口 HTTP %s：%s" % (exc.code, exc.reason))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError("视觉接口不可达或超时：%s" % exc)
    try:
        answer = payload["choices"][0]["message"]["content"]
        data = parse_json_answer(answer)
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("视觉接口响应缺少 choices/message：%s" % exc)
    return data, payload.get("usage", {})


def edit_image(cfg, images, prompt, size="1024x1024", quality="high"):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ProviderError("缺少 openai Python SDK，请安装 Skill 的 requirements.txt") from exc
    client = OpenAI(api_key=cfg["key"], base_url=cfg["base_url"])
    handles = [Path(image).open("rb") for image in images]
    try:
        try:
            response = client.images.edit(model=cfg["model"], image=handles, prompt=prompt,
                                          size=size, quality=quality, output_format="png")
        except TypeError:
            # Some OpenAI-compatible gateways do not accept output_format.
            for handle in handles:
                handle.seek(0)
            response = client.images.edit(model=cfg["model"], image=handles, prompt=prompt,
                                          size=size, quality=quality)
    except Exception as exc:
        raise ProviderError("生图接口失败：%s: %s" % (type(exc).__name__, str(exc)[:300]))
    finally:
        for handle in handles:
            handle.close()
    if not getattr(response, "data", None) or not response.data[0].b64_json:
        raise ProviderError("生图接口没有返回 b64_json 图片")
    return base64.b64decode(response.data[0].b64_json), getattr(response, "usage", None)
