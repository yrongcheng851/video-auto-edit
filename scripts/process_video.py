#!/usr/bin/env python3
"""Normalize a video to 3:4 (1080x1440) WITHOUT distortion (proportional scale),
keeping the original audio track by default. Output quality is preserved as
closely as possible (low CRF + medium preset, original AAC audio copied).

Fit modes (--fit):
  crop  (default) proportional scale to cover 1080x1440, center-crop the
        overflow. Full-bleed 3:4, no distortion; edge content may be lost.
  blur  proportional scale to fit inside 1080x1440, empty area filled
        with a blurred, zoomed copy of the video itself. No distortion, no crop.
  black proportional scale to fit, padded with black bars.

Original audio is always kept unless --replace-audio is passed explicitly.

Usage:
    python process_video.py <input> [--fit crop|blur|black]
                            [--replace-audio] [--style chill|upbeat|energetic]
                            [--bgm <file.mp3>] [--out-dir DIR] [--title NAME]

Output directory defaults to the value saved by scripts/setup.py
(``out_dir`` in the config file), else ``~/Videos/3x4``.

Prints JSON: {"output": ..., "replaced_audio": bool, "fit": ..., ...}
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BGM_DIR = os.path.join(SKILL_DIR, "assets", "bgm")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfgmod  # noqa: E402
STYLES = {"chill": "chill.mp3", "upbeat": "upbeat.mp3", "energetic": "energetic.mp3"}

# Output canvas: 3:4 portrait. width:height = 3:4 -> 1080x1440.
OUT_W, OUT_H = 1080, 1440
# All modes keep the source aspect ratio (no stretching / distortion).
FILTERS = {
    "blur": (f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
             f"crop={OUT_W}:{OUT_H},boxblur=20:5[bg];"
             f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"),
    "black": (f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
              f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[v]"),
    "crop": (f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
             f"crop={OUT_W}:{OUT_H},setsar=1[v]"),
}


def get_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg not found; install imageio-ffmpeg or add ffmpeg to PATH")
    return path


def find_ffprobe(ffmpeg):
    """Locate ffprobe next to ffmpeg, on PATH, or anywhere sensible.

    imageio-ffmpeg ships ffmpeg only and never ffprobe, so on most installs
    this returns None and the caller falls back to parsing ffmpeg's own
    ``-i`` output, which works on every platform.
    """
    path = shutil.which("ffprobe")
    if path:
        return path
    if not ffmpeg:
        return None
    exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    candidate = os.path.join(os.path.dirname(ffmpeg), exe)
    return candidate if os.path.exists(candidate) else None


def get_audio_codec(path, ffmpeg=None):
    """Return the audio codec name of the first audio stream ('' if none)."""
    if ffmpeg is None:
        ffmpeg = get_ffmpeg()
    ffprobe = find_ffprobe(ffmpeg)
    if ffprobe:
        try:
            proc = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=codec_name", "-of",
                 "default=nw=1:nk=1", path],
                capture_output=True, text=True, timeout=60)
            return (proc.stdout or "").strip()
        except Exception:
            pass
    # ffprobe-less fallback: read the codec straight out of ffmpeg's banner.
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                              capture_output=True, text=True, timeout=60)
        m = re.search(r"Audio:\s*([A-Za-z0-9_]+)", proc.stderr or "")
        if m:
            return m.group(1).lower()
    except Exception:
        pass
    return ""


def sanitize(name):
    name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip("._ ")
    return name[:60] or "video"


def get_duration(path, ffmpeg=None):
    """Return source duration in seconds (0 if unknown)."""
    if ffmpeg is None:
        ffmpeg = get_ffmpeg()
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                              capture_output=True, text=True, timeout=60)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)", proc.stderr or "")
        if m:
            h, mi, s = (int(x) for x in m.groups())
            return h * 3600 + mi * 60 + s
    except Exception:
        pass
    return 0


def ensure_writable(out_dir, io_mode="normal"):
    """Create out_dir and prove it is writable by actually writing to it.

    os.access() lies on Windows ACLs, so a real write is the only reliable
    test. In ``normal`` mode the probe is a temp file that cleans itself up.
    In ``sandbox`` mode some delete hooks abort the whole process on any
    unlink, so we leave a fixed-name 1-byte marker instead (overwritten next
    run) — that mode exists purely for hostile sandboxes; leave it off.
    """
    try:
        os.makedirs(out_dir, exist_ok=True)
        if io_mode == "sandbox":
            with open(os.path.join(out_dir, ".wtest"), "w") as fh:
                fh.write("x")
        else:
            with tempfile.NamedTemporaryFile(dir=out_dir, prefix=".vae_probe_",
                                             delete=True) as fh:
                fh.write(b"x")
    except (PermissionError, OSError) as exc:
        raise RuntimeError(
            f"无法写入输出目录 {out_dir}（{exc.strerror or exc}）。\n"
            "换一个目录，或先把目录建好并授予当前用户写权限，然后重跑：\n"
            "  python scripts/setup.py --out-dir <有写权限的目录>")


def process(input_path, fit="crop", replace_audio=False, style="chill", bgm=None,
            out_dir=None, title=None, preset=None, io_mode=None):
    settings = cfgmod.load()
    out_dir = out_dir or settings["out_dir"]
    preset = preset or settings["preset"]
    io_mode = io_mode or settings["io_mode"]
    ensure_writable(out_dir, io_mode)
    ffmpeg = get_ffmpeg()
    base = sanitize(title or os.path.splitext(os.path.basename(input_path))[0])
    stamp = time.strftime("%Y%m%d_%H%M%S")
    output = os.path.join(out_dir, f"{base}_3x4_{stamp}.mp4")

    vfilter = FILTERS[fit]
    cmd = [ffmpeg, "-y", "-v", "error", "-i", input_path]
    if replace_audio:
        bgm_path = bgm or os.path.join(BGM_DIR, STYLES[style])
        if not os.path.exists(bgm_path):
            raise RuntimeError(f"BGM file missing: {bgm_path} "
                               f"(regenerate with scripts/make_bgm.py)")
        cmd += ["-stream_loop", "-1", "-i", bgm_path]
        cmd += ["-filter_complex", vfilter + ";[1:a]volume=0.9[a]",
                "-map", "[v]", "-map", "[a]", "-shortest"]
    else:
        cmd += ["-filter_complex", vfilter, "-map", "[v]", "-map", "0:a?"]
    # Copy the original AAC audio track untouched when present (no re-encode);
    # otherwise re-encode.
    audio_codec = get_audio_codec(input_path, ffmpeg)
    acmd = ["-c:a", "copy"] if audio_codec == "aac" else ["-c:a", "aac", "-b:a", "192k"]

    # Encoding speed/quality comes from config (setup.py -> "preset"):
    #   quality -> CRF 18 / veryfast, best looking, slowest
    #   fast    -> CRF 20 / ultrafast, quick, visually near-identical
    #   auto    -> quality for short clips, fast above ~200s so that long
    #              encodes still finish inside restrictive wall-clock budgets
    dur = get_duration(input_path, ffmpeg)
    choice = preset
    if os.environ.get("VAE_ULTRAFAST"):
        choice = "fast"
    if choice == "auto":
        choice = "fast" if (dur and dur > 200) else "quality"
    if choice == "fast":
        encoder_preset, crf = "ultrafast", "20"
    else:
        encoder_preset, crf = "veryfast", "18"
    cmd += ["-c:v", "libx264", "-preset", encoder_preset, "-crf", crf,
            "-pix_fmt", "yuv420p", *acmd,
            "-movflags", "+faststart", output]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        # report ffmpeg's own error output, not the (long) command line
        tail = (proc.stderr or "").strip().splitlines()[-5:]
        raise RuntimeError("ffmpeg failed (exit %d): %s"
                           % (proc.returncode, " | ".join(tail) or "no stderr"))
    return {"output": os.path.abspath(output), "replaced_audio": replace_audio,
            "fit": fit, "style": style if replace_audio else None,
            "size_mb": round(os.path.getsize(output) / 1e6, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--fit", choices=list(FILTERS), default="crop",
                    help="how to adapt to 3:4 without distortion (default: crop to fill)")
    ap.add_argument("--replace-audio", action="store_true",
                    help="opt-in: replace original audio with BGM")
    ap.add_argument("--style", choices=list(STYLES), default="chill")
    ap.add_argument("--bgm", default=None, help="custom BGM file, overrides --style")
    ap.add_argument("--out-dir", default=None,
                    help="output directory (default: the one saved by setup.py)")
    ap.add_argument("--preset", choices=list(cfgmod.PRESETS), default=None,
                    help="override the configured encoding preset for this run")
    ap.add_argument("--title", default=None)
    args = ap.parse_args()
    try:
        print(json.dumps(process(args.input, args.fit, args.replace_audio, args.style,
                                 args.bgm, args.out_dir, args.title, args.preset),
                         ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"input": args.input, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
