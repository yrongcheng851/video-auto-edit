#!/usr/bin/env python3
"""Generate the built-in royalty-free BGM tracks (chill / upbeat / energetic).

Tracks are procedurally synthesized with numpy (chord pads + bass + hats), so
they are 100% original and copyright-free. Re-run any time to regenerate:

    python make_bgm.py            # writes assets/bgm/{chill,upbeat,energetic}.mp3

Users can also drop their own .mp3 files into assets/bgm/ with the same names
(or pass --bgm to process_video.py) to override.
"""
import os
import shutil
import subprocess
import wave

import numpy as np

SR = 44100
SECONDS = 32
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets", "bgm")


def note(name):
    names = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
             "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    if len(name) > 1 and name[1] == "#":
        key, octv = name[:2], int(name[2:])
    else:
        key, octv = name[:1], int(name[1:])
    return 440.0 * 2 ** ((names[key] + 12 * octv - 69) / 12)


def env_adsr(n, a, d, s, r, level=1.0):
    a_n, d_n, r_n = int(a * SR), int(d * SR), int(r * SR)
    s_n = max(n - a_n - d_n - r_n, 0)
    e = np.concatenate([
        np.linspace(0, level, a_n, endpoint=False),
        np.linspace(level, level * s, d_n, endpoint=False),
        np.full(s_n, level * s),
        np.linspace(level * s, 0, r_n)])
    return e[:n] if len(e) >= n else np.pad(e, (0, n - len(e)))


def tone(freq, dur, kind="pad", gain=0.2):
    n = int(dur * SR)
    t = np.arange(n) / SR
    if kind == "pad":
        sig = (np.sin(2 * np.pi * freq * t)
               + 0.4 * np.sin(2 * np.pi * freq * 2 * t)
               + 0.15 * np.sin(2 * np.pi * freq * 3.01 * t))
        e = env_adsr(n, 0.3, 0.3, 0.7, 0.5)
    elif kind == "pluck":
        sig = np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * freq * 2 * t)
        e = np.exp(-t * 6)
    elif kind == "bass":
        sig = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * freq * 0.5 * t)
        e = env_adsr(n, 0.01, 0.1, 0.8, 0.1)
    else:
        sig, e = np.sin(2 * np.pi * freq * t), np.ones(n)
    return sig * e * gain


def hat(dur=0.05, gain=0.08):
    n = int(dur * SR)
    rng = np.random.default_rng(7)
    return rng.standard_normal(n).astype(np.float64) * np.exp(-np.arange(n) / SR * 60) * gain


def render(chords, bpm, bar_beats, chord_kind, bass_pattern, hats, total_s=SECONDS):
    beat = 60.0 / bpm
    bar = beat * bar_beats
    n = int(total_s * SR)
    mix = np.zeros(n)

    def add(sig, start):
        i = int(start * SR)
        mix[i:i + len(sig)] += sig[:max(0, min(len(sig), n - i))]

    t, ci = 0.0, 0
    while t < total_s:
        root, quality = chords[ci % len(chords)]
        intervals = {"maj": [0, 4, 7, 11], "min": [0, 3, 7, 10]}[quality]
        base = note(root)
        for iv in intervals:
            add(tone(base * 2 ** (iv / 12), bar, chord_kind), t)
        if bass_pattern == "whole":
            add(tone(base / 2, bar, "bass", 0.25), t)
        elif bass_pattern == "eighth":
            for b in range(int(bar_beats * 2)):
                add(tone(base / 2, beat / 2, "bass", 0.3), t + b * beat / 2)
        if hats:
            for b in range(int(bar_beats * (2 if hats == "eighth" else 1))):
                add(hat(), t + b * beat / (2 if hats == "eighth" else 1) + beat / 2)
        t += bar
        ci += 1
    mix *= 0.9 / max(1e-6, np.abs(mix).max())
    return (mix * 32767).astype(np.int16)


def save_mp3(pcm, path):
    wav_path = path[:-4] + ".wav"
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg = shutil.which("ffmpeg")
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", wav_path,
                    "-c:a", "libmp3lame", "-b:a", "192k", path], check=True)
    os.remove(wav_path)


TRACKS = {
    "chill": dict(  # 舒缓: Cmaj7 - Am7 - Fmaj7 - G7, slow pads
        chords=[("C4", "maj"), ("A3", "min"), ("F3", "maj"), ("G3", "maj")],
        bpm=72, bar_beats=4, chord_kind="pad", bass_pattern="whole", hats=None),
    "upbeat": dict(  # 轻快: C - G - Am - F plucks
        chords=[("C4", "maj"), ("G3", "maj"), ("A3", "min"), ("F3", "maj")],
        bpm=116, bar_beats=4, chord_kind="pluck", bass_pattern="whole", hats="beat"),
    "energetic": dict(  # 动感: Am - F - C - G, driving eighth bass + hats
        chords=[("A3", "min"), ("F3", "maj"), ("C4", "maj"), ("G3", "maj")],
        bpm=128, bar_beats=4, chord_kind="pluck", bass_pattern="eighth", hats="eighth"),
}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, cfg in TRACKS.items():
        path = os.path.join(OUT, name + ".mp3")
        save_mp3(render(**cfg), path)
        print("wrote", path, f"{os.path.getsize(path)/1e3:.0f} KB")


if __name__ == "__main__":
    main()
