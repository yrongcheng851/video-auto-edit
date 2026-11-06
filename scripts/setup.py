#!/usr/bin/env python3
"""First-run setup for video-auto-edit.

Fills in the handful of things that cannot be guessed on someone else's
machine: where processed videos should land, and (optionally) the path to a
Netscape cookies.txt for login-walled sources.

    python scripts/setup.py              # interactive wizard
    python scripts/setup.py --show       # print the current effective config
    python scripts/setup.py --check      # environment check only, no writes
    python scripts/setup.py --yes        # accept defaults, no questions

Every question can also be answered by a flag, so this works unattended:
    python scripts/setup.py --out-dir ~/Videos/3x4 --cookies ~/cookies.txt \
                            --preset auto --io-mode normal
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfgmod  # noqa: E402

REQUIRED_MODULES = ("yt_dlp", "requests", "numpy", "imageio_ffmpeg")
LINE = "-" * 62


# --------------------------------------------------------------------------- #
# environment check
# --------------------------------------------------------------------------- #
def check_environment():
    """Print what works and what is missing. Returns a list of problems."""
    problems = []

    print("环境自检")
    print(LINE)
    py = sys.version_info
    ok_py = py >= (3, 9)
    print(f"  Python      {py.major}.{py.minor}.{py.micro}"
          f"  {'OK' if ok_py else '请升级到 3.9+'}")
    if not ok_py:
        problems.append("Python 版本过低（需要 3.9+）")

    for mod in REQUIRED_MODULES:
        try:
            __import__(mod)
            print(f"  {mod:<11} OK")
        except ImportError:
            print(f"  {mod:<11} 缺失 → pip install {mod.replace('_', '-')}")
            problems.append(f"缺少依赖 {mod}")

    ffmpeg = None
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        print(f"  ffmpeg      OK  {ffmpeg}")
    else:
        print("  ffmpeg      未找到 → pip install imageio-ffmpeg")
        problems.append("找不到 ffmpeg")

    ffprobe = find_ffprobe(ffmpeg)
    if ffprobe:
        print(f"  ffprobe     OK  {ffprobe}")
    else:
        print("  ffprobe     未找到（不影响使用，音频/时长会走 ffmpeg 解析回退）")

    print(LINE)
    return problems


def find_ffprobe(ffmpeg):
    """Cross-platform ffprobe lookup; None means 'use the ffmpeg fallback'."""
    path = shutil.which("ffprobe")
    if path:
        return path
    if not ffmpeg:
        return None
    exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    candidate = os.path.join(os.path.dirname(ffmpeg), exe)
    return candidate if os.path.exists(candidate) else None


# --------------------------------------------------------------------------- #
# prompt helpers
# --------------------------------------------------------------------------- #
def ask(question, default=None, validator=None):
    """Ask one question. Returns default on EOF / non-interactive / empty input."""
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            raw = input(f"  {question}{suffix}\n  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if not raw:
            return default
        if validator:
            problem = validator(raw)
            if problem:
                print(f"  ✗ {problem}\n")
                continue
        return raw


def ask_choice(question, choices, default):
    print(f"  {question}")
    for i, (key, desc) in enumerate(choices, 1):
        mark = "*" if key == default else " "
        print(f"    {mark}{i}) {key:<8} {desc}")
    while True:
        try:
            raw = input(f"  选择 1-{len(choices)} [{default}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1][0]
        for key, _ in choices:
            if raw == key:
                return key
        print("  ✗ 输入无效，试试序号或名字\n")


_PROBE_SNIPPET = """\
import os, sys, tempfile
d = sys.argv[1]
f = tempfile.NamedTemporaryFile(dir=d, prefix=".vae_probe_", delete=False)
f.write(b"x")
f.close()
print("WROTE", flush=True)
try:
    os.remove(f.name)
    print("CLEANED", flush=True)
except OSError:
    pass
"""


def validate_out_dir(path):
    """Check the directory exists, is writable, and report what happened.

    The probe runs in a child process on purpose: some sandboxed environments
    abort the *entire* process on any unlink, so isolating it means the wizard
    survives and can still tell you whether the write itself worked.
    """
    expanded = os.path.expanduser(os.path.expandvars(path))
    try:
        os.makedirs(expanded, exist_ok=True)
    except (PermissionError, OSError) as exc:
        return f"建不了这个目录（{exc.strerror or exc}）"
    try:
        proc = subprocess.run([sys.executable, "-c", _PROBE_SNIPPET, expanded],
                              capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return f"写入测试失败：{exc}"
    out = (proc.stdout or "") + (proc.stderr or "")
    if "WROTE" not in out:
        detail = (proc.stderr or "").strip().splitlines()[-1:] or ["未知原因"]
        return f"这个目录写不进去（{detail[0]}），换一个或调整权限"
    return None


def validate_cookies(path):
    """Accept only a Netscape cookies.txt that actually carries a session."""
    expanded = os.path.expanduser(os.path.expandvars(path))
    if not os.path.isfile(expanded):
        return f"文件不存在：{expanded}"
    try:
        with open(expanded, encoding="utf-8", errors="ignore") as fh:
            text = fh.read(200_000)
    except OSError as exc:
        return f"读不了这个文件：{exc}"
    if "# Netscape HTTP Cookie File" not in text and "\t" not in text:
        return "这不像 Netscape 格式的 cookies.txt，请用 Get cookies.txt LOCALLY 导出"
    return None


def describe_cookies(path):
    """Best-effort summary: which domains does this file cover?"""
    expanded = os.path.expanduser(os.path.expandvars(path))
    domains = set()
    try:
        with open(expanded, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    domains.add(parts[0].lstrip("."))
    except OSError:
        return "无法读取"
    if not domains:
        return "文件里没有有效 cookie 行"
    covered = []
    if any("xiaohongshu" in d for d in domains):
        covered.append("小红书")
    if any("douyin" in d or "bytedance" in d for d in domains):
        covered.append("抖音")
    tag = "、".join(covered) if covered else "未包含小红书/抖音"
    return f"{len(domains)} 个域，{tag}"


# --------------------------------------------------------------------------- #
# show
# --------------------------------------------------------------------------- #
def show(current):
    print("当前生效配置")
    print(LINE)
    print(f"  配置文件      {current['_path'] or '（未初始化，全部使用默认值）'}")
    print(f"  输出目录      {current['out_dir']}")
    cookie = current.get("cookies")
    print(f"  cookies       {cookie + '  —  ' + describe_cookies(cookie) if cookie else '未设置（遇到登录墙时再补）'}")
    preset_desc = {
        "auto": "短片子用高质量，超过约 200 秒自动降速保成功",
        "quality": "始终 CRF 18 / veryfast —— 画质最好，最慢",
        "fast": "始终 CRF 20 / ultrafast —— 快，画质肉眼几乎无差",
    }
    print(f"  编码预设      {current['preset']}  ({preset_desc[current['preset']]})")
    io_desc = {
        "normal": "正常清理临时探针文件",
        "sandbox": "不删探针，兼容会拦截删除的沙箱环境",
    }
    print(f"  IO 模式       {current['io_mode']}  ({io_desc[current['io_mode']]})")
    print(LINE)
    for key, env in cfgmod.ENV_VARS.items():
        print(f"  环境变量可覆盖：{env}")
    print(LINE)


# --------------------------------------------------------------------------- #
# wizard
# --------------------------------------------------------------------------- #
def wizard(current, args):
    interactive = sys.stdin.isatty() and not args.yes

    print()
    print("video-auto-edit 初始化")
    print("=" * 62)
    if not interactive:
        print("（非交互模式：直接采用传入参数与默认值）")
    print()

    out_dir = args.out_dir
    if out_dir is None:
        default = current["out_dir"]
        if interactive:
            print("[1/4] 处理好的视频存到哪？")
            while True:
                answer = ask("直接回车沿用默认值；也可以拖一个文件夹进来", default)
                if answer is None:
                    out_dir = default
                    break
                problem = validate_out_dir(answer)
                if problem:
                    print(f"  ✗ {problem}\n")
                    continue
                out_dir = os.path.expanduser(os.path.expandvars(answer))
                print(f"  ✓ 可写\n")
                break
        else:
            out_dir = default
    else:
        problem = validate_out_dir(out_dir)
        if problem:
            print(f"✗ 输出目录：{problem}", file=sys.stderr)
            return None
        out_dir = os.path.expanduser(os.path.expandvars(out_dir))

    cookies = args.cookies if args.cookies is not None else current.get("cookies")
    if interactive:
        print("[2/4] cookies（可选）")
        print("      小红书经常要登录才给视频地址。需要的话，用浏览器扩展")
        print("      「Get cookies.txt LOCALLY」登录后导出 Netscape 格式文件，把路径贴进来。")
        print("      暂时不需要就直接回车跳过，以后随时重跑本向导补上。")
        while True:
            answer = ask("cookies.txt 路径（留空=不用）", cookies or "")
            if not answer:
                cookies = None
                break
            problem = validate_cookies(answer)
            if problem:
                print(f"  ✗ {problem}\n")
                continue
            cookies = os.path.expanduser(os.path.expandvars(answer))
            print(f"  ✓ {describe_cookies(cookies)}\n")
            break
    if cookies:
        problem = validate_cookies(cookies)
        if problem:
            print(f"✗ cookies：{problem}", file=sys.stderr)
            return None
        cookies = os.path.expanduser(os.path.expandvars(cookies))

    preset = args.preset or current["preset"]
    if interactive and not args.preset:
        print("[3/4] 编码预设")
        preset = ask_choice("画质和速度怎么平衡？", [
            ("auto", "短片子保画质，长片子自动降速保成功（推荐）"),
            ("quality", "始终最高画质，编码更慢"),
            ("fast", "始终优先速度，画质肉眼几乎无差"),
        ], preset)
        print()

    io_mode = args.io_mode or current["io_mode"]
    if interactive and not args.io_mode:
        print("[4/4] 兼容模式")
        io_mode = ask_choice("运行在会拦截文件删除的沙箱里吗？", [
            ("normal", "不是，正常清理临时文件（推荐）"),
            ("sandbox", "是，保留一个 1 字节探针不删，避免整个进程被打断"),
        ], io_mode)
        print()

    new_cfg = {
        "_path": current["_path"],
        "out_dir": out_dir,
        "cookies": cookies,
        "preset": preset,
        "io_mode": io_mode,
    }
    saved = cfgmod.save(new_cfg, explicit=args.config)
    print(LINE)
    print(f"✓ 配置已写入 {saved}")
    print(LINE)
    for key, env in cfgmod.ENV_VARS.items():
        print(f"  临时覆盖可用环境变量 {env}")
    print()
    print("接下来可以跑：")
    print('    python scripts/pipeline.py "https://xhslink.cn/o/xxxx"')
    print()
    return new_cfg


def main():
    ap = argparse.ArgumentParser(description="video-auto-edit 初始化 / 查看配置")
    ap.add_argument("--show", action="store_true", help="打印当前配置后退出")
    ap.add_argument("--check", action="store_true", help="只做环境自检，不写配置")
    ap.add_argument("--yes", "-y", action="store_true", help="非交互，全用默认值")
    ap.add_argument("--out-dir", help="输出目录")
    ap.add_argument("--cookies", help="Netscape cookies.txt 路径；传空字符串表示不设置")
    ap.add_argument("--preset", choices=cfgmod.PRESETS, help="编码预设")
    ap.add_argument("--io-mode", choices=cfgmod.IO_MODES, help="IO 兼容模式")
    ap.add_argument("--config", help="指定配置文件路径（默认 ~/.video-auto-edit/config.json）")
    args = ap.parse_args()

    current = cfgmod.load()

    if args.show:
        show(current)
        return 0

    problems = check_environment()
    if args.check:
        return 1 if problems else 0
    if problems:
        print("先把上面标了问题的依赖装上，再回来跑一次本向导。", file=sys.stderr)
        return 1

    if args.cookies == "":
        args.cookies = None

    result = wizard(current, args)
    if result is None:
        return 1
    print()
    show({**cfgmod.load(), "_path": cfgmod.write_target(args.config)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
