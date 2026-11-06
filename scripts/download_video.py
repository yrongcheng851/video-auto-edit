#!/usr/bin/env python3
"""Download videos from Douyin / Xiaohongshu share links.

Usage:
    python download_video.py "<share text or url>" [<url2> ...] --out <dir> [--cookies cookies.txt]

Prints one JSON line per downloaded video:
    {"url": ..., "file": ..., "title": ..., "source": "douyin|xhs"}

Notes:
- Douyin: handled by yt-dlp (supports douyin.com / iesdouyin.com share links).
- Xiaohongshu: yt-dlp has no XHS extractor, so a built-in fallback fetches the
  note page and digs the video CDN url out of window.__INITIAL_STATE__.
  XHS frequently requires login; pass --cookies <netscape cookies.txt> exported
  from a logged-in browser when the anonymous fetch fails.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

URL_RE = re.compile(r"https?://[^\s，。\"'）)》>]+")

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def extract_urls(text):
    return [u.rstrip(".,;") for u in URL_RE.findall(text)]


def is_xhs(url):
    return ("xiaohongshu.com" in url or "xhslink.com" in url
            or "xhslink.cn" in url)


def _ytdlp_download(url, outdir, cookies=None):
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--restrict-filenames",
        "-o", os.path.join(outdir, "%(extractor)s_%(id)s.%(ext)s"),
        "--print", "after_move:filepath",
        "--quiet", "--no-warnings",
    ]
    if cookies:
        cmd += ["--cookies", cookies]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    path = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    if proc.returncode != 0 or not path or not os.path.exists(path):
        raise RuntimeError("yt-dlp failed: " + (proc.stderr.strip() or "no output file")[:400])
    return path


def _load_cookie_header(cookies_path):
    """Convert a Netscape cookies.txt into a Cookie header string."""
    pairs = []
    with open(cookies_path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 7:
                pairs.append(f"{parts[5]}={parts[6].strip()}")
    return "; ".join(pairs)


def _find_video_url(obj, hits):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("http") and (
                    "sns-video" in v or "xhscdn" in v and ".mp4" in v or k in ("masterUrl", "backupUrl")):
                hits.append(v.replace("\\u002F", "/"))
            else:
                _find_video_url(v, hits)
    elif isinstance(obj, list):
        for item in obj:
            _find_video_url(item, hits)


def _normalize_xhs_url(url):
    """Some share links (e.g. HarmonyOS app_platform=harmony) redirect to a
    generic /explore?...&target_note_id=<id> page where the note id lives in a
    query param instead of the path. yt-dlp can't handle that, and the page
    HTML often hides the video behind a login wall. Rewriting to the canonical
    /explore/<id> note page fixes both."""
    m = re.search(r"[?&](?:target_note_id|note_id)=([0-9a-f]+)", url)
    if m and not re.search(r"/(?:explore|discovery/item)/[0-9a-f]{8,}", url):
        return f"https://www.xiaohongshu.com/explore/{m.group(1)}"
    return url


def _fetch_xhs_html(url, headers):
    """Resolve the share link, normalize HarmonyOS explore?...&target_note_id=
    style links to the canonical note page, and return (html, final_url)."""
    import requests
    resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
    proper = _normalize_xhs_url(resp.url)
    if proper != resp.url:
        resp = requests.get(proper, headers=headers, timeout=30, allow_redirects=True)
    return resp.text, resp.url


def _parse_video_url(html):
    video_urls = []
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if m:
        raw = m.group(1).replace("undefined", "null")
        try:
            _find_video_url(json.loads(raw), video_urls)
        except json.JSONDecodeError:
            pass
    if not video_urls:
        video_urls = re.findall(r'https?[^"\'\\\s]*sns-video[^"\'\\\s]*', html)
    return video_urls


def _xhs_download(url, outdir, cookies=None):
    import requests

    headers = {"User-Agent": UA, "Referer": "https://www.xiaohongshu.com/"}
    if cookies:
        headers["Cookie"] = _load_cookie_header(cookies)

    # XHS anonymous fetch is flaky: sometimes returns a login-wall page with no
    # video url. Retry the fetch+parse a few times before giving up.
    last_err = None
    html = final_url = None
    for attempt in range(3):
        try:
            html, final_url = _fetch_xhs_html(url, headers)
            video_urls = _parse_video_url(html)
            if video_urls:
                break
            last_err = RuntimeError("XHS page did not expose a video url (login wall?).")
        except Exception as e:  # transient network errors
            last_err = e
        if attempt < 2:
            import time
            time.sleep(2 * (attempt + 1))
    else:
        raise last_err or RuntimeError("XHS fetch failed.")
    if not video_urls:
        raise RuntimeError(
            "XHS page did not expose a video url (login wall?). "
            "Retry with --cookies <cookies.txt> exported from a logged-in browser.")

    vid_url = video_urls[0].replace("http://", "https://")
    vid = requests.get(vid_url, headers=headers, timeout=120, stream=True)
    vid.raise_for_status()
    note_id = re.search(r"/(?:item|discovery/item|explore)/([0-9a-f]+)", final_url)
    name = "xhs_" + (note_id.group(1) if note_id else re.sub(r"\W+", "", url)[-16:]) + ".mp4"
    path = os.path.join(outdir, name)
    with open(path, "wb") as fh:
        for chunk in vid.iter_content(1 << 20):
            fh.write(chunk)
    if os.path.getsize(path) < 50_000:
        os.remove(path)
        raise RuntimeError("XHS download suspiciously small, likely blocked; use --cookies.")
    return path


def download_one(url, outdir, cookies=None):
    os.makedirs(outdir, exist_ok=True)
    before = set(glob.glob(os.path.join(outdir, "*")))
    if is_xhs(url):
        try:
            path = _xhs_download(url, outdir, cookies)
            source = "xhs"
        except Exception as e:
            # last resort: some XHS mirrors work through yt-dlp generic extractor
            try:
                path = _ytdlp_download(url, outdir, cookies)
                source = "xhs"
            except Exception:
                raise e
    else:
        path = _ytdlp_download(url, outdir, cookies)
        source = "douyin" if ("douyin" in url or "iesdouyin" in url) else "other"
    return {"url": url, "file": os.path.abspath(path), "title": os.path.basename(path),
            "source": source}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("links", nargs="+", help="share text or urls")
    ap.add_argument("--out", required=True, help="download directory")
    ap.add_argument("--cookies", default=None,
                    help="Netscape cookies.txt (needed for XHS login wall); "
                         "defaults to the path saved by setup.py")
    args = ap.parse_args()

    if not args.cookies:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import config as cfgmod
        args.cookies = cfgmod.load().get("cookies")

    urls = []
    for item in args.links:
        urls.extend(extract_urls(item) if not os.path.isfile(item) else
                    [l.strip() for l in open(item, encoding="utf-8") if l.strip()])
    if not urls:
        print(json.dumps({"error": "no urls found in input"}))
        sys.exit(2)

    ok = True
    for u in urls:
        try:
            print(json.dumps(download_one(u, args.out, args.cookies), ensure_ascii=False))
        except Exception as e:
            ok = False
            print(json.dumps({"url": u, "error": str(e)[:500]}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
