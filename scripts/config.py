#!/usr/bin/env python3
"""Shared configuration for video-auto-edit.

Everything machine-specific lives here, not baked into the pipeline scripts.
Run ``setup.py`` once after cloning to fill this in.

Where the config file is looked up (first existing wins):
  1. $VAE_CONFIG
  2. ~/.video-auto-edit/config.json     (per-user, survives skill upgrades)
  3. <skill>/config.json               (portable mode, travels with the folder)

Where it is written when you run ``setup.py``:
  1. $VAE_CONFIG (if set)
  2. ~/.video-auto-edit/config.json

Resolution order for each individual setting (highest first):
  CLI flag > environment variable > config file > built-in default
"""
from __future__ import annotations

import json
import os
import sys

APP_DIR = os.path.join(os.path.expanduser("~"), ".video-auto-edit")
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_NAME = "config.json"

#: preset   - encoding speed/quality trade-off
#:             auto    = short clips get quality, anything over ~200s drops to fast
#:             quality = always CRF 18 / veryfast (best looking, slowest)
#:             fast    = always CRF 20 / ultrafast (quick, visibly fine)
PRESETS = ("auto", "quality", "fast")

#: io_mode  - how strictly we handle temporary probe files
#:             normal  = clean up after ourselves (default, use this)
#:             sandbox = leave a 1-byte .wtest marker instead of deleting, for
#:                       sandboxes whose delete hook aborts the whole process
IO_MODES = ("normal", "sandbox")

DEFAULTS = {
    "out_dir": None,      # None -> default_out_dir()
    "cookies": None,      # path to a Netscape cookies.txt, optional
    "preset": "auto",
    "io_mode": "normal",
}

ENV_VARS = {
    "out_dir": "VAE_OUT_DIR",
    "cookies": "VAE_COOKIES",
    "preset": "VAE_PRESET",
    "io_mode": "VAE_IO_MODE",
}


def default_out_dir():
    """Somewhere universally writable: ~/Videos/3x4."""
    return os.path.join(os.path.expanduser("~"), "Videos", "3x4")


def find_config(explicit=None):
    """Return the path of the first config file that exists, or None."""
    candidates = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("VAE_CONFIG"):
        candidates.append(os.environ["VAE_CONFIG"])
    candidates.append(os.path.join(APP_DIR, CONFIG_NAME))
    candidates.append(os.path.join(SKILL_DIR, CONFIG_NAME))
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def write_target(explicit=None):
    """Return the path ``save()`` should write to."""
    if explicit:
        return explicit
    if os.environ.get("VAE_CONFIG"):
        return os.environ["VAE_CONFIG"]
    return os.path.join(APP_DIR, CONFIG_NAME)


def _expand(value):
    if not isinstance(value, str) or not value:
        return value
    return os.path.expanduser(os.path.expandvars(value))


def load():
    """Return the merged settings dict. Never raises."""
    cfg = dict(DEFAULTS)
    path = find_config()
    if path:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
        except Exception as exc:  # malformed config should not kill a batch
            print(f"[config] 读取 {path} 失败，回退到默认值：{exc}", file=sys.stderr)
    cfg["_path"] = path

    for key, env in ENV_VARS.items():
        override = os.environ.get(env)
        if override:
            cfg[key] = override

    cfg["out_dir"] = _expand(cfg.get("out_dir")) or default_out_dir()
    cfg["cookies"] = _expand(cfg.get("cookies")) or None
    if cfg.get("preset") not in PRESETS:
        cfg["preset"] = DEFAULTS["preset"]
    if cfg.get("io_mode") not in IO_MODES:
        cfg["io_mode"] = DEFAULTS["io_mode"]
    return cfg


def save(cfg, explicit=None):
    """Persist only the known keys, creating the directory if needed."""
    path = write_target(explicit)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    data = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def pick(cli_value, key, cfg):
    """CLI value if given, else the configured one."""
    if cli_value not in (None, ""):
        return cli_value
    return cfg.get(key)


def is_first_run():
    return find_config() is None


def first_run_hint():
    return (
        "尚未初始化：还没有找到配置文件。\n"
        "先跑一次向导，选好保存目录（如需下载登录墙内容再贴 cookies）：\n"
        "    python scripts/setup.py\n"
        "现在这轮先用默认值继续 → 输出到 "
        f"{default_out_dir()}"
    )


if __name__ == "__main__":
    import pprint

    current = load()
    pprint.pprint(current)
