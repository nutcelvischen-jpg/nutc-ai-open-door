#!/usr/bin/env python3
"""Build frame-accurate stereo soundtrack with earshot launch-kit SFX + ambient pad and mux into MP4."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
import soxr
from scipy.signal import butter, sosfilt

ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / ".bin"
if BIN_DIR.exists():
    os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ.get("PATH", "")

from earshot.forge import kit, sfx  # noqa: E402

SR = 48000
FOLDER = ROOT / "videos" / "nutc_open_door"
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def make_ambient_pad(n_samples: int, sr: int = SR) -> np.ndarray:
    """Create a warm, voice-friendly stereo harmonic ambient pad (-35 LUFS target)."""
    t = np.arange(n_samples, dtype=np.float64) / sr
    # Gentle progression: Cmaj9 -> Fmaj9 -> Am9 -> G6 across 16s phrases
    chords = [
        [130.81, 196.00, 246.94, 293.66],  # C3, G3, B3, D4
        [174.61, 220.00, 261.63, 329.63],  # F3, A3, C4, E4
        [110.00, 164.81, 246.94, 293.66],  # A2, E3, B3, D4
        [98.00, 196.00, 246.94, 329.63],   # G2, G3, B3, E4
    ]
    seg_len = 8.0
    pad_l = np.zeros(n_samples, dtype=np.float64)
    pad_r = np.zeros(n_samples, dtype=np.float64)

    for idx, freqs in enumerate(chords):
        # Soft cosine crossfade weight for every occurrence of chord idx in 32s cycle
        phase = ((t - idx * seg_len) % (len(chords) * seg_len)) / seg_len
        mask = (phase >= 0.0) & (phase < 1.0)
        w = np.where(mask, np.maximum(0.0, np.sin(np.pi * phase)) ** 1.2, 0.0)
        # Overlap smooth transitions using shifted half-cycles
        for f_i, freq in enumerate(freqs):
            detune = 1.0 + (f_i - 1.5) * 0.0014
            lfo = 0.85 + 0.15 * np.sin(2.0 * np.pi * (0.11 + f_i * 0.03) * t + f_i)
            s_l = np.sin(2.0 * np.pi * freq * t + f_i * 0.7) * lfo
            s_r = np.sin(2.0 * np.pi * (freq * detune) * t + f_i * 1.3) * lfo
            amp = 0.25 if f_i == 0 else 0.16
            pad_l += w * amp * s_l
            pad_r += w * amp * s_r

    # Add a soft continuous root drone so crossfades never dip to zero
    drone_l = 0.22 * np.sin(2.0 * np.pi * 65.41 * t) + 0.10 * np.sin(2.0 * np.pi * 130.81 * t + 0.4)
    drone_r = 0.22 * np.sin(2.0 * np.pi * 65.41 * t + 0.3) + 0.10 * np.sin(2.0 * np.pi * 130.81 * t + 1.1)
    stereo = np.stack([pad_l + drone_l, pad_r + drone_r], axis=1)

    # Low-pass under 850 Hz so vocal presence (1-4 kHz) stays completely clear
    sos = butter(3, 850.0, btype="low", fs=sr, output="sos")
    stereo = sosfilt(sos, stereo, axis=0)

    # Envelope: 0.8s fade-in, 2.8s fade-out
    env = np.ones(n_samples, dtype=np.float64)
    fi = min(n_samples, int(0.8 * sr))
    fo = min(n_samples, int(2.8 * sr))
    env[:fi] = np.sin(np.linspace(0, np.pi / 2, fi)) ** 2
    env[-fo:] = np.cos(np.linspace(0, np.pi / 2, fo)) ** 2
    stereo *= env[:, None]

    # Normalize pad to gentle -34.0 LUFS
    meter = pyln.Meter(sr)
    loud = meter.integrated_loudness(stereo)
    if np.isfinite(loud):
        stereo *= 10.0 ** ((-34.0 - loud) / 20.0)
    return stereo


def main() -> None:
    tl = json.loads((FOLDER / "timeline_zh.json").read_text(encoding="utf-8"))
    total_s = float(tl["total"])
    n_samples = int(round(total_s * SR))

    # 1. Initialize, render, and audit earshot launch kit
    kit_json = FOLDER / "audio_kit" / "kit.json"
    kit_dir = FOLDER / "audio_kit" / "takes"
    kit_dir.mkdir(parents=True, exist_ok=True)
    init_res = kit.init("launch", str(kit_json), force=True)
    print("✓ earshot kit init:", init_res["summary"])
    lock = kit.render(str(kit_json), str(kit_dir))
    print("✓ earshot kit render:", lock["summary"])
    audit = kit.check(str(kit_json), str(kit_dir))
    print("✓ earshot kit check:", audit["summary"])
    if not audit["ok"]:
        raise RuntimeError(f"earshot kit audit failed: {audit['summary']}")

    # 2. Load & normalize narration to -16.5 LUFS stereo 48 kHz
    nar_mono, nar_sr = sf.read(str(FOLDER / "narration_zh.wav"), dtype="float64")
    if nar_mono.ndim == 2:
        nar_mono = nar_mono.mean(axis=1)
    if nar_sr != SR:
        nar_mono = soxr.resample(nar_mono, nar_sr, SR)
    if len(nar_mono) < n_samples:
        nar_mono = np.pad(nar_mono, (0, n_samples - len(nar_mono)))
    else:
        nar_mono = nar_mono[:n_samples]
    nar = np.stack([nar_mono, nar_mono], axis=1)

    meter = pyln.Meter(SR)
    nar_loud = meter.integrated_loudness(nar)
    nar *= 10.0 ** ((-16.5 - nar_loud) / 20.0)

    # 3. Ambient pad
    bed = make_ambient_pad(n_samples, SR)

    # 4. Schedule earshot cues aligned to exact timeline_zh.json timestamps
    S = lambda i: float(tl["scenes"][i]["start"])
    L = lambda i, j: float(tl["scenes"][i]["lines"][j]["start"])
    LE = lambda i, j: float(tl["scenes"][i]["lines"][j]["end"])
    LM = lambda i, j, k=0.5: L(i, j) + (LE(i, j) - L(i, j)) * k

    cues = [
        ("land.light", S(0), -18.0),
        ("tick.crisp", L(0, 1) + 0.10, -16.0),
        ("snap", LM(0, 1, 0.52), -14.0),
        ("swell", L(0, 2) - 0.12, -16.0),
        ("hit", L(0, 2) - 0.12, -13.5),
        ("bell", L(0, 2) + 0.12, -17.0),
        ("whoosh.short", S(1) - 0.12, -17.0),
        ("land", LM(1, 0, 0.45), -16.5),
        ("land", LM(1, 0, 0.85), -16.5),
        ("land", LM(1, 1, 0.70), -16.5),
        ("pop", L(1, 3) - 0.05, -17.0),
        ("whoosh.short", S(2) - 0.12, -17.0),
    ]
    for k in range(6):
        cues.append(("tick", L(2, 1) - 0.10 + k * 0.09, -19.5))
    cues.extend([
        ("click.confirm", L(2, 3) - 0.05, -16.0),
        ("whoosh.short", S(3) - 0.12, -17.0),
    ])
    for k in range(7):
        cues.append(("key", LM(3, 0, 0.72) + k * 0.16, -21.0))
    for k in range(3):
        cues.append(("tock", L(3, 2) + k * 0.45, -18.5))
    cues.extend([
        ("whoosh.short", S(4) - 0.12, -17.0),
        ("land.light", L(4, 0) + 0.15, -17.5),
        ("pop", L(4, 2), -17.5),
        ("pop", L(4, 2) + 0.25, -17.5),
        ("click.confirm", L(4, 3) + 1.25, -14.5),
        ("whoosh.short", S(5) - 0.12, -17.0),
        ("land", LM(5, 0, 0.45), -16.5),
        ("land", L(5, 1), -16.5),
        ("land", LM(5, 1, 0.55), -16.5),
        ("land", L(5, 2), -15.5),
        ("whoosh.short", S(6) - 0.12, -17.0),
        ("pop", L(6, 0) + 0.10, -17.5),
        ("pop", LM(6, 0, 0.58), -17.5),
        ("pop", L(6, 1) + 0.15, -17.5),
        ("swell", L(6, 2) - 0.12, -16.0),
        ("bell", L(6, 2) + 0.18, -16.5),
    ])

    sfx_bus = np.zeros((n_samples, 2), dtype=np.float64)
    placed_count = 0
    for idx, (role, cue_s, cap_db) in enumerate(cues):
        r_lock = lock["roles"].get(role)
        if not r_lock or not r_lock["takes"]:
            continue
        take = r_lock["takes"][idx % len(r_lock["takes"])]
        y, y_sr = sf.read(str(kit_dir / take["file"]), always_2d=True, dtype="float64")
        if y_sr != SR:
            y = soxr.resample(y, y_sr, SR)
        if y.shape[1] == 1:
            y = np.repeat(y, 2, axis=1)
        else:
            y = y[:, :2]

        start_s = kit.place(take, r_lock, cue_s)
        # Respect bed_db guidance while capping below vocal level
        try:
            b_lvl = kit.bed_level(bed, max(1.05, cue_s), SR)
        except Exception:
            b_lvl = None
        g_db = min(kit.gain_db(take, r_lock, b_lvl), cap_db)
        y = y * (10.0 ** (g_db / 20.0))

        s0 = int(round(start_s * SR))
        if s0 < 0:
            y = y[-s0:]
            s0 = 0
        s1 = min(n_samples, s0 + len(y))
        if s1 > s0:
            sfx_bus[s0:s1] += y[: s1 - s0]
            placed_count += 1

    # 5. Sum buses & soft-limit peaks <= -1.5 dBFS
    mix = nar + bed + sfx_bus
    ceiling = 10.0 ** (-1.5 / 20.0)
    pk = float(np.abs(mix).max())
    if pk > ceiling:
        mix *= ceiling / pk

    final_lufs = float(meter.integrated_loudness(mix))
    final_peak_db = float(20.0 * np.log10(np.abs(mix).max() + 1e-12))

    master_wav = FOLDER / "master_mix_zh.wav"
    sf.write(str(master_wav), mix, SR, subtype="PCM_24")
    print(f"✓ Placed {placed_count} earshot SFX cues")
    print(f"✓ Master mix saved: {master_wav}")
    print(f"✓ Audio metrics: integrated={final_lufs:.2f} LUFS, peak={final_peak_db:.2f} dBFS, sr={SR} Hz, channels=2")

    # 6. Mux into rendered MP4 if available
    mp4_path = FOLDER / "out" / "nutc_open_door_zh.mp4"
    if mp4_path.exists():
        tmp_mp4 = FOLDER / "out" / "nutc_open_door_zh_video_only.mp4"
        shutil.move(str(mp4_path), str(tmp_mp4))
        cmd = [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(tmp_mp4),
            "-i",
            str(master_wav),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(mp4_path),
        ]
        subprocess.run(cmd, check=True)
        tmp_mp4.unlink()
        print(f"✓ Muxed master audio into: {mp4_path} ({mp4_path.stat().st_size / (1024*1024):.2f} MB)")
    else:
        print("△ Video file not yet present; skipping mux:", mp4_path)


if __name__ == "__main__":
    main()
