#!/usr/bin/env python3
"""Detect distracting background noise (hiss / hum / crowd / wind) in a video's audio track.

Heuristic (no ML models, stdlib + numpy only):
  1. Extract audio to 16 kHz mono WAV via ffmpeg.
  2. STFT -> per-frame spectral flatness and energy.
  3. Two signals of background noise:
     - QUIET-FRAME FLATNESS (primary): in the quietest 30% of frames, speech/music
       energy collapses but hiss stays broadband -> flatness stays high (> 0.25).
     - SNR (secondary, only when flatness is moderately elevated): ratio of
       loud-frame (p95) to quiet-frame (p10) energy compressed below 8 dB.
       (SNR alone is NOT decisive: constant-amplitude signals like tones or
       steady music score ~0 dB without being noisy.)

Usage:
    python detect_noise.py <video> [--force] [--json]

Exit code 0 always; decision is in the JSON output: {"noisy": true/false, ...}
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np


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


def extract_audio(video, sr=16000):
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    subprocess.run(
        [get_ffmpeg(), "-y", "-v", "error", "-i", video,
         "-vn", "-ac", "1", "-ar", str(sr), tmp.name],
        check=True, timeout=300)
    with wave.open(tmp.name, "rb") as w:
        n = w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    os.unlink(tmp.name)
    return data, sr


def analyze(video):
    samples, sr = extract_audio(video)
    if samples.size < sr:
        return {"video": video, "noisy": False, "reason": "audio too short or missing",
                "quiet_flatness": None, "snr_db": None}

    n_fft, hop = 2048, 512
    win = np.hanning(n_fft).astype(np.float32)
    n_frames = 1 + (samples.size - n_fft) // hop
    if n_frames < 10:
        return {"video": video, "noisy": False, "reason": "audio too short",
                "quiet_flatness": None, "snr_db": None}

    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = samples[idx] * win
    spec = np.abs(np.fft.rfft(frames, axis=1)) + 1e-10
    energy = (spec ** 2).sum(axis=1)
    flat = np.exp(np.mean(np.log(spec), axis=1)) / np.mean(spec, axis=1)

    quiet_thr = np.percentile(energy, 30)
    quiet_flat = float(np.median(flat[energy <= quiet_thr]))
    loud_e = np.percentile(energy, 95)
    quiet_e = max(np.percentile(energy, 10), 1e-12)
    snr_db = float(10 * np.log10(loud_e / quiet_e))

    noisy = quiet_flat > 0.25 or (quiet_flat > 0.12 and snr_db < 8.0)
    reasons = []
    if quiet_flat > 0.25:
        reasons.append(f"quiet-frame spectral flatness {quiet_flat:.2f} > 0.25 (hiss/hum)")
    elif quiet_flat > 0.12 and snr_db < 8.0:
        reasons.append(f"flatness {quiet_flat:.2f} + SNR {snr_db:.1f} dB (constant background noise)")
    return {"video": video, "noisy": noisy,
            "quiet_flatness": round(quiet_flat, 3), "snr_db": round(snr_db, 1),
            "reason": "; ".join(reasons) if reasons else "audio clean"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--force", action="store_true",
                    help="skip analysis, always report noisy (force BGM replacement)")
    args = ap.parse_args()
    if args.force:
        result = {"video": args.video, "noisy": True, "reason": "forced by --force",
                  "quiet_flatness": None, "snr_db": None}
    else:
        try:
            result = analyze(args.video)
        except Exception as e:
            result = {"video": args.video, "noisy": False,
                      "reason": f"analysis failed: {e}", "quiet_flatness": None, "snr_db": None}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
