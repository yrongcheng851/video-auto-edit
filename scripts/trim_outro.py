#!/usr/bin/env python3
"""Detect and cut the outro watermark card at the end of a short video.

Short videos downloaded from Xiaohongshu/Douyin often end with a 2-5s
platform/author watermark card (e.g. "related notes", "follow for more").
This script scans the last `--tail-sec` seconds, finds the first frame where
the picture changes abruptly AND then stays still (a static card), and cuts
the video just before that point with a stream copy (lossless, fast).

Heuristic, not 100% accurate. Use `--fallback-sec` for a fixed cut when
detection is unreliable, or `--no-trim` to only report what it would do.

Corner author logos are NOT handled here: the 3:4 crop-to-fill step in
process_video.py already crops them out of frame, so no extra work is needed.

Prints JSON: {"trimmed", "cut_at", "reason", "output"}
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

try:
    import numpy as np
except Exception:
    np = None


def get_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    p = shutil.which("ffmpeg")
    if not p:
        raise RuntimeError("ffmpeg not found; install imageio-ffmpeg or add ffmpeg to PATH")
    return p


def probe(path):
    """Return (duration, width, height) for the first video stream, using
    ffmpeg only (imageio-ffmpeg does not ship ffprobe)."""
    ffmpeg = get_ffmpeg()
    proc = subprocess.run([ffmpeg, "-v", "info", "-i", path],
                          capture_output=True, text=True, timeout=60)
    txt = proc.stderr or ""
    dur = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    w = h = 0
    m2 = re.search(
        r"Stream\s+#\d+:\d+(?:\([^)]*\))?:\s*Video:\s*\S+\s+.*?(\d{2,5})x(\d{2,5})",
        txt)
    if m2:
        w, h = int(m2.group(1)), int(m2.group(2))
    return dur, w, h


def extract_gray_frames(path, start, tail, fps, scale_w=240):
    """Extract grayscale downscaled frames as a (N, H, W) float32 numpy array."""
    ffmpeg = get_ffmpeg()
    _, w, h = probe(path)
    if w > 0 and h > 0:
        scale_h = max(2, round(h * scale_w / w))
    else:
        scale_h = 320
    if scale_h % 2:
        scale_h += 1
    vf = f"format=gray,scale={scale_w}:{scale_h},fps={fps}"
    cmd = [ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-i", path,
           "-t", f"{tail:.3f}", "-vf", vf, "-pix_fmt", "gray",
           "-f", "rawvideo", "-an", "-"]
    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("frame extraction failed: " +
                           (proc.stderr or b"").decode(errors="ignore")[:200])
    frame_bytes = scale_w * scale_h
    data = np.frombuffer(proc.stdout, dtype=np.uint8)
    n = len(data) // frame_bytes
    if n == 0:
        raise RuntimeError("no frames extracted")
    return data[:n * frame_bytes].reshape(n, scale_h, scale_w).astype(np.float32)


def find_outro(frames, fps):
    """Return (time_offset, end_card) where time_offset is the seconds from the
    scan start of the first frame that looks like an outro card start:
      - a sudden change followed by a stable (static) region, OR
      - a sudden change within the final ~1.5s of the video (an end-card: the
        video ends ON the card, so there is no room for a stable window after).
    Returns (None, False) if nothing is found.
    """
    diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))  # len N-1
    if diffs.size < 3:
        return None, False
    base = diffs.mean()
    std = diffs.std()
    jump_thr = max(base + 2.0 * std, 6.0)       # gray 0-255 scale
    stable_thr = max(base * 0.5, 1.5)
    look = max(1, int(fps))                      # ~1s of stability required
    n = len(diffs)
    for i in range(n):
        if diffs[i] >= jump_thr:
            after = diffs[i + 1: i + 1 + look]
            if after.size and after.mean() <= stable_thr:
                return (i + 1) / fps, False
            # End-card: a large jump so close to the end that the video ends on
            # the card (no stable window can be measured after the jump).
            remaining = (n - i) / fps
            if remaining <= 1.5:
                return (i + 1) / fps, True
    return None, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--tail-sec", type=float, default=12,
                    help="scan the last N seconds for an outro card")
    ap.add_argument("--min-outro", type=float, default=0.3,
                    help="minimum detected outro length to actually cut "
                         "(very short end-cards are still cut via the end-card rule)")
    ap.add_argument("--fallback-sec", type=float, default=0,
                    help="if detection finds nothing, cut this many seconds off "
                         "the end (0 = do not cut when nothing detected)")
    ap.add_argument("--lead", type=float, default=0.3,
                    help="cut this many seconds BEFORE the detected card start, "
                         "so stream-copy keyframe alignment never leaves card frames")
    ap.add_argument("--fps", type=float, default=3, help="frame sample rate")
    ap.add_argument("--out", default=None, help="output path (default: <in>_trim.mp4)")
    ap.add_argument("--no-trim", action="store_true",
                    help="only report detection, do not cut")
    args = ap.parse_args()

    try:
        if np is None:
            raise RuntimeError("numpy missing; install it in the venv")
        dur, _, _ = probe(args.input)
        if dur <= 0:
            raise RuntimeError("cannot read duration")
        tail = min(args.tail_sec, max(2.0, dur * 0.4))
        start = max(0.0, dur - tail)

        frames = extract_gray_frames(args.input, start, tail, args.fps)
        off, end_card = find_outro(frames, args.fps)
        cut_at = None
        reason = ""
        if off is not None:
            cand = start + off
            if end_card or dur - cand >= args.min_outro:
                cut_at = max(0.0, cand - args.lead)
                kind = "end-card" if end_card else "outro card"
                reason = f"{kind} detected at {cand:.2f}s (len {dur - cand:.2f}s)"
            else:
                reason = f"jump at {cand:.2f}s but shorter than min-outro, kept"
        else:
            reason = "no stable outro card detected"

        if cut_at is None:
            if args.fallback_sec > 0 and dur > args.fallback_sec:
                cut_at = max(0.0, dur - args.fallback_sec)
                reason += f"; fallback cut {args.fallback_sec:.1f}s"
            else:
                print(json.dumps({"trimmed": False, "cut_at": None,
                                  "reason": reason, "output": args.input},
                                 ensure_ascii=False))
                return

        if args.no_trim:
            print(json.dumps({"trimmed": True, "cut_at": round(cut_at, 2),
                              "reason": reason, "output": args.input},
                             ensure_ascii=False))
            return

        ffmpeg = get_ffmpeg()
        out = args.out or (os.path.splitext(args.input)[0] + "_trim.mp4")
        tmp = out + ".part.mp4"
        cmd = [ffmpeg, "-v", "error", "-i", args.input, "-t", f"{cut_at:.3f}",
               "-c", "copy", "-movflags", "+faststart", tmp]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0 or not os.path.exists(tmp):
            raise RuntimeError("cut failed: " +
                               (proc.stderr or "").strip().splitlines()[-3:])
        os.replace(tmp, out)
        actual = probe(out)[0]
        print(json.dumps({"trimmed": True, "cut_at": round(actual, 2),
                          "reason": reason, "output": os.path.abspath(out)},
                         ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"input": args.input, "error": str(e)[:400],
                          "trimmed": False, "output": args.input},
                         ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
