#!/usr/bin/env python3
"""End-to-end pipeline: link(s) -> download -> 3:4 (proportional, no distortion)
-> keep original audio -> configured output directory

Single:   python pipeline.py "分享文本或链接" [--fit crop|blur|black]
Batch:    python pipeline.py --file links.txt
          python pipeline.py "url1" "url2" "url3"

Output directory, cookies path and encoding preset come from the config file
written by scripts/setup.py. Run that once first on a new machine.

Audio: original audio is ALWAYS kept by default. Opt-in music replacement:
  --replace-music   detect background noise first, replace only if noisy
  --force-music     always replace audio with BGM, skip detection

One JSON summary line per video:
  {"url", "downloaded", "replaced_audio", "fit", "output", "error?"}
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as cfgmod  # noqa: E402


def run(script, *args):
    proc = subprocess.run([sys.executable, os.path.join(HERE, script), *args],
                          capture_output=True, text=True, timeout=1800)
    lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    if not lines:
        raise RuntimeError(f"{script} produced no output: {proc.stderr[:300]}")
    return [json.loads(l) for l in lines]


def handle(url, workdir, args):
    rec = {"url": url}
    dl = run("download_video.py", url, "--out", workdir,
             *(["--cookies", args.cookies] if args.cookies else []))[0]
    if "error" in dl:
        rec["error"] = "download: " + dl["error"]
        return rec
    rec["downloaded"] = dl["file"]

    # Step: cut the outro watermark card (platform/author card at the very end).
    # Corner author logos are handled later by the 3:4 crop-to-fill in
    # process_video.py, so only the trailing card is cut here.
    work = dl["file"]
    if not args.no_trim_outro:
        trim_args = ["--tail-sec", str(args.tail_sec),
                     "--min-outro", str(args.min_outro),
                     "--lead", str(args.lead)]
        if args.fallback_sec:
            trim_args += ["--fallback-sec", str(args.fallback_sec)]
        trim = run("trim_outro.py", dl["file"], *trim_args)[0]
        rec["trimmed"] = trim.get("trimmed")
        rec["trim_cut_at"] = trim.get("cut_at")
        rec["trim_reason"] = trim.get("reason")
        if "error" in trim:
            rec["error"] = "trim_outro: " + trim["error"]
            return rec
        work = trim.get("output", dl["file"])

    # default: keep original audio. Only opt-in paths touch the audio track.
    replace = False
    if args.force_music:
        replace = True
        rec["noise_detail"] = "forced by --force-music"
    elif args.replace_music:
        det = run("detect_noise.py", dl["file"])[0]
        rec["noisy"] = det["noisy"]
        rec["noise_detail"] = det.get("reason")
        replace = bool(det["noisy"])

    proc = run("process_video.py", work,
               "--fit", args.fit,
               *(["--replace-audio", "--style", args.style] if replace else []),
               "--out-dir", args.out_dir, "--title",
               os.path.splitext(os.path.basename(dl["file"]))[0])[0]
    if "error" in proc:
        rec["error"] = "process: " + proc["error"]
        return rec
    rec.update({"replaced_audio": proc["replaced_audio"], "fit": proc["fit"],
                "output": proc["output"], "style": proc["style"],
                "size_mb": proc["size_mb"]})
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("links", nargs="*", help="share text / urls")
    ap.add_argument("--file", help="text file with one url per line (batch mode)")
    ap.add_argument("--fit", choices=["crop", "blur", "black"], default="crop",
                    help="3:4 fit mode without distortion (default: crop to fill)")
    ap.add_argument("--replace-music", action="store_true",
                    help="opt-in: detect noise and replace audio with BGM only if noisy")
    ap.add_argument("--force-music", action="store_true",
                    help="opt-in: always replace audio with BGM, skip detection")
    ap.add_argument("--style", choices=["chill", "upbeat", "energetic"], default="chill",
                    help="BGM style (only used with --replace-music / --force-music)")
    ap.add_argument("--cookies", default=None,
                    help="Netscape cookies.txt for login-walled sites (XHS). "
                         "Defaults to the path saved by setup.py.")
    ap.add_argument("--no-trim-outro", action="store_true",
                    help="skip cutting the trailing outro watermark card")
    ap.add_argument("--tail-sec", type=float, default=12,
                    help="scan the last N seconds of each video for an outro card")
    ap.add_argument("--min-outro", type=float, default=0.3,
                    help="minimum detected outro length to actually cut "
                         "(short end-cards are still cut via the end-card rule)")
    ap.add_argument("--lead", type=float, default=0.3,
                    help="cut this many seconds before the detected card start")
    ap.add_argument("--fallback-sec", type=float, default=0,
                    help="if no card is detected, cut this many seconds off the "
                         "end (0 = keep as-is)")
    ap.add_argument("--out-dir", default=None,
                    help="output directory (default: the one saved by setup.py)")
    ap.add_argument("--keep-tmp", action="store_true", help="keep downloaded originals")
    args = ap.parse_args()

    settings = cfgmod.load()
    args.out_dir = cfgmod.pick(args.out_dir, "out_dir", settings)
    args.cookies = cfgmod.pick(args.cookies, "cookies", settings)
    if cfgmod.is_first_run():
        print(cfgmod.first_run_hint(), file=sys.stderr)

    urls = list(args.links)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            urls += [l.strip() for l in fh if l.strip() and not l.startswith("#")]
    if not urls:
        print(json.dumps({"error": "no input links"}))
        sys.exit(2)

    workdir = tempfile.mkdtemp(prefix="vae_")
    results, failed = [], 0
    try:
        for u in urls:
            try:
                rec = handle(u, workdir, args)
            except Exception as e:
                rec = {"url": u, "error": str(e)[:500]}
            if "error" in rec:
                failed += 1
            results.append(rec)
            print(json.dumps(rec, ensure_ascii=False), flush=True)
    finally:
        if not args.keep_tmp:
            shutil.rmtree(workdir, ignore_errors=True)
    sys.exit(1 if failed == len(urls) else 0)


if __name__ == "__main__":
    main()
