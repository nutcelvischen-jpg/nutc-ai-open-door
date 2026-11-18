#!/usr/bin/env python3
"""Generate warm Taiwanese Mandarin narration via per-line edge-tts + scipy DSP."""
import asyncio
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import edge_tts
import numpy as np
from scipy.signal import butter, sosfiltfilt

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FOLDER = ROOT / "videos" / "nutc_open_door"


def load_script(folder: Path) -> dict:
    """Load script.json from video project folder."""
    return json.loads((folder / "script.json").read_text(encoding="utf-8"))


def say(line) -> str:
    """Return spoken TTS string from line string or [spoken, caption] tuple."""
    return line[0] if isinstance(line, list) else line


def show(line) -> str:
    """Return on-screen caption string from line string or [spoken, caption] tuple."""
    return line[1] if isinstance(line, list) else line

RATE = 24000
VOICE = "zh-TW-HsiaoYuNeural"
TTS_RATE = "-2%"

LEAD_IN = 0.40
LINE_GAP = 0.28
SCENE_GAP = 0.48
TAIL = 2.60

BREATH_ROOM_S = 0.045
FADE_S = 0.018
LOWPASS_HZ = 8200.0
HIGHPASS_HZ = 60.0


async def synthesize_mp3(text: str, mp3_path: Path, retries: int = 3) -> None:
    """Synthesize one narration line via edge-tts with simple retry."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            comm = edge_tts.Communicate(text, voice=VOICE, rate=TTS_RATE)
            await comm.save(str(mp3_path))
            if mp3_path.stat().st_size > 256:
                return
            raise RuntimeError(f"Empty MP3 output for {text!r}")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            await asyncio.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"edge-tts failed for {text!r}: {last_err}")


def mp3_to_float64(mp3_path: Path) -> np.ndarray:
    """Decode MP3 to 24 kHz mono float64 samples via ffmpeg."""
    cmd = [
        str(FFMPEG),
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(mp3_path),
        "-ar",
        str(RATE),
        "-ac",
        "1",
        "-f",
        "f32le",
        "pipe:1",
    ]
    res = subprocess.run(cmd, capture_output=True, check=True)
    return np.frombuffer(res.stdout, dtype=np.float32).astype(np.float64)


def apply_vocal_warmth(samples: np.ndarray) -> np.ndarray:
    """Apply zero-phase sub-bass cleanup and gentle 8.2 kHz low-pass for vocal warmth."""
    if len(samples) < 32:
        return samples
    cleaned = samples - np.mean(samples)
    sos_hp = butter(2, HIGHPASS_HZ, btype="high", fs=RATE, output="sos")
    sos_lp = butter(3, LOWPASS_HZ, btype="low", fs=RATE, output="sos")
    warm = sosfiltfilt(sos_hp, cleaned)
    warm = sosfiltfilt(sos_lp, warm)
    peak = float(np.max(np.abs(warm)))
    if peak > 0.96:
        warm *= 0.96 / peak
    return warm


def trim_and_fade(samples: np.ndarray) -> np.ndarray:
    """Trim edge silence gently while preserving 45ms breath room and 18ms cosine fades."""
    win = max(1, int(round(0.005 * RATE)))  # 5ms analysis frame
    breath = int(round(BREATH_ROOM_S * RATE))
    fade_n = int(round(FADE_S * RATE))

    n_frames = len(samples) // win
    if n_frames < 4:
        return samples

    frames = samples[: n_frames * win].reshape(n_frames, win)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    peak = np.max(np.abs(frames), axis=1)
    active = (rms > 0.0045) | (peak > 0.011)

    if not np.any(active):
        out = samples.copy()
    else:
        idx = np.flatnonzero(active)
        s0 = max(0, int(idx[0]) * win - breath)
        e0 = min(len(samples), (int(idx[-1]) + 1) * win + breath)
        out = samples[s0:e0].copy()

    if len(out) > 2 * fade_n + 4:
        u = np.linspace(0.0, np.pi, fade_n)
        fade_in = 0.5 * (1.0 - np.cos(u))
        fade_out = 0.5 * (1.0 + np.cos(u))
        out[:fade_n] *= fade_in
        out[-fade_n:] *= fade_out
    return out


def float_to_pcm16(samples: np.ndarray) -> bytes:
    """Convert normalized float64 samples to 16-bit signed little-endian PCM bytes."""
    clipped = np.clip(np.round(samples * 32767.0), -32768, 32767).astype("<i2")
    return clipped.tobytes()


def write_wav(path: Path, samples: np.ndarray) -> None:
    """Write 24 kHz 16-bit mono WAV file."""
    pcm = float_to_pcm16(samples)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


async def run_all() -> None:
    data = load_script(FOLDER)
    out_dir = FOLDER / "audio_zh"
    out_dir.mkdir(parents=True, exist_ok=True)

    lead_in_n = int(round(LEAD_IN * RATE))
    line_gap_n = int(round(LINE_GAP * RATE))
    scene_gap_n = int(round(SCENE_GAP * RATE))
    tail_n = int(round(TAIL * RATE))

    cursor = lead_in_n
    merged_chunks = [np.zeros(lead_in_n, dtype=np.float64)]
    tl = {
        "lang": "zh",
        "voice": VOICE,
        "rate": TTS_RATE,
        "lead_in": LEAD_IN,
        "line_gap": LINE_GAP,
        "gap": SCENE_GAP,
        "tail": TAIL,
        "scenes": [],
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        scenes = data["scenes"]
        for sc_idx, sc in enumerate(scenes):
            sc_id = sc["id"]
            sc_start_sample = cursor
            sc_chunks: list[np.ndarray] = []
            line_entries: list[dict] = []

            lines = sc["zh"]
            for ln_idx, line in enumerate(lines):
                spoken = say(line)
                caption = show(line)
                mp3_path = tmp_dir / f"{sc_id}_{ln_idx:02d}.mp3"
                print(f"→ [{sc_id} #{ln_idx + 1}] {spoken}")
                await synthesize_mp3(spoken, mp3_path)

                raw = mp3_to_float64(mp3_path)
                processed = trim_and_fade(apply_vocal_warmth(raw))

                line_start_s = round(cursor / RATE, 3)
                cursor += len(processed)
                line_end_s = round(cursor / RATE, 3)

                sc_chunks.append(processed)
                line_entries.append({
                    "text": spoken,
                    "sub": caption,
                    "start": line_start_s,
                    "end": line_end_s,
                })

                if ln_idx < len(lines) - 1:
                    sc_chunks.append(np.zeros(line_gap_n, dtype=np.float64))
                    cursor += line_gap_n

            scene_audio = np.concatenate(sc_chunks)
            wav_path = out_dir / f"{sc_id}.wav"
            write_wav(wav_path, scene_audio)

            sc_dur_s = round(len(scene_audio) / RATE, 3)
            tl["scenes"].append({
                "id": sc_id,
                "start": round(sc_start_sample / RATE, 3),
                "dur": sc_dur_s,
                "lines": line_entries,
            })
            merged_chunks.append(scene_audio)
            print(f"  ✓ {sc_id}.wav ({sc_dur_s:.3f}s, {len(lines)} lines)")

            if sc_idx < len(scenes) - 1:
                merged_chunks.append(np.zeros(scene_gap_n, dtype=np.float64))
                cursor += scene_gap_n

    merged_chunks.append(np.zeros(tail_n, dtype=np.float64))
    cursor += tail_n
    full_audio = np.concatenate(merged_chunks)
    tl["total"] = round(len(full_audio) / RATE, 3)

    nar_path = FOLDER / "narration_zh.wav"
    write_wav(nar_path, full_audio)
    tl_path = FOLDER / "timeline_zh.json"
    tl_path.write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")

    meta = {"common": data["meta"]["common"], "zh": data["meta"]["zh"], "langs": data["langs"]}
    tl_js = (
        "window.TIMELINES=" + json.dumps({"zh": tl}, ensure_ascii=False) + ";\n"
        "window.META=" + json.dumps(meta, ensure_ascii=False) + ";\n"
    )
    tl_js_path = FOLDER / "_tl.js"
    tl_js_path.write_text(tl_js, encoding="utf-8")

    print(f"\n✓ Built {nar_path.name}, {tl_path.name} & {tl_js_path.name} — total duration: {tl['total']:.3f}s")
    for sc in tl["scenes"]:
        print(f"  {sc['id']}: start={sc['start']:.3f}s dur={sc['dur']:.3f}s ({len(sc['lines'])} lines)")


if __name__ == "__main__":
    asyncio.run(run_all())
