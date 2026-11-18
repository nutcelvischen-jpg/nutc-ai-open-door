#!/usr/bin/env python3
"""Generate natural Taiwanese Mandarin narration via OpenRouter google/gemini-3.8-flash-tts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FOLDER = ROOT / "videos" / "nutc_open_door"
KEY_FILE = Path("/Users/chenchunchih/Desktop/數據視覺化/OPR-KEY.txt")

OPENROUTER_URL = "https://openrouter.ai/api/v1/audio/speech"
MODEL = "google/gemini-3.8-flash-tts"
VOICE = "Zephyr"

RATE = 24000
LEAD_IN = 0.40
LINE_GAP = 0.28
SCENE_GAP = 0.48
TAIL = 2.60

BREATH_ROOM_S = 0.045
FADE_S = 0.018
LOWPASS_HZ = 10600.0
HIGHPASS_HZ = 60.0


def load_script(folder: Path) -> dict:
    """Load script.json from video project folder."""
    return json.loads((folder / "script.json").read_text(encoding="utf-8"))


def say(line) -> str:
    """Return spoken TTS string from line string or [spoken, caption] tuple."""
    return line[0] if isinstance(line, list) else line


def show(line) -> str:
    """Return on-screen caption string from line string or [spoken, caption] tuple."""
    return line[1] if isinstance(line, list) else line


def discover_api_keys() -> list[str]:
    """Load OpenRouter API keys dynamically from env and OPR-KEY.txt without hardcoding."""
    keys: list[str] = []
    env_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if env_key:
        keys.append(env_key)
    if KEY_FILE.exists():
        raw = KEY_FILE.read_text(encoding="utf-8")
        for match in re.findall(r"sk-or-v1-[0-9a-f]{64}", raw):
            if match not in keys:
                keys.append(match)
    if not keys:
        raise RuntimeError(f"No OpenRouter API keys found in environment or {KEY_FILE}")
    return keys


def decode_audio_bytes(raw: bytes, content_type: str) -> bytes:
    """Normalize returned audio (raw PCM or encoded audio) into 24 kHz mono s16le PCM bytes."""
    ct = (content_type or "").lower()
    if "audio/pcm" in ct:
        rate_match = re.search(r"rate=(\d+)", ct)
        ch_match = re.search(r"channels=(\d+)", ct)
        src_rate = int(rate_match.group(1)) if rate_match else RATE
        src_ch = int(ch_match.group(1)) if ch_match else 1
        if src_rate == RATE and src_ch == 1:
            return raw
        with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as tf:
            tf.write(raw)
            tmp_path = Path(tf.name)
        try:
            cmd = [
                str(FFMPEG),
                "-y",
                "-loglevel",
                "error",
                "-f",
                "s16le",
                "-ar",
                str(src_rate),
                "-ac",
                str(src_ch),
                "-i",
                str(tmp_path),
                "-ar",
                str(RATE),
                "-ac",
                "1",
                "-f",
                "s16le",
                "pipe:1",
            ]
            return subprocess.run(cmd, capture_output=True, check=True).stdout
        finally:
            tmp_path.unlink(missing_ok=True)

    ext = ".wav" if "wav" in ct else ".mp3"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
        tf.write(raw)
        tmp_path = Path(tf.name)
    try:
        cmd = [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(tmp_path),
            "-ar",
            str(RATE),
            "-ac",
            "1",
            "-f",
            "s16le",
            "pipe:1",
        ]
        return subprocess.run(cmd, capture_output=True, check=True).stdout
    finally:
        tmp_path.unlink(missing_ok=True)


def synthesize_line(
    text: str,
    instructions: str,
    keys: list[str],
    cache_dir: Path,
    retries: int = 4,
) -> np.ndarray:
    """Fetch 24 kHz mono float64 samples from OpenRouter Gemini 3.8 TTS with cache & failover."""
    sig_src = json.dumps({"model": MODEL, "voice": VOICE, "instructions": instructions, "input": text}, ensure_ascii=False)
    digest = hashlib.sha256(sig_src.encode("utf-8")).hexdigest()[:24]
    pcm_path = cache_dir / f"{digest}.pcm"

    if pcm_path.exists() and pcm_path.stat().st_size > 256:
        pcm_bytes = pcm_path.read_bytes()
        return np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float64) / 32768.0

    payload = json.dumps(
        {
            "model": MODEL,
            "input": text,
            "voice": VOICE,
            "instructions": instructions,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    last_err: Exception | None = None
    for attempt in range(retries):
        for key_idx, key in enumerate(keys):
            req = urllib.request.Request(
                OPENROUTER_URL,
                data=payload,
                method="POST",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://nutcelvischen-jpg.github.io/nutc-ai-open-door/",
                    "X-OpenRouter-Title": "NUTC Open Another Door",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    status = getattr(resp, "status", 200)
                    ct = resp.headers.get("Content-Type", "")
                    body = resp.read()
                    if status != 200 or len(body) <= 256:
                        raise RuntimeError(f"Unexpected HTTP {status}, bytes={len(body)}")
                    if "json" in ct.lower():
                        raise RuntimeError(f"Unexpected JSON error body: {body[:300]!r}")
                    pcm_bytes = decode_audio_bytes(body, ct)
                    if len(pcm_bytes) <= 256:
                        raise RuntimeError("Decoded PCM audio is empty")
                    pcm_path.write_bytes(pcm_bytes)
                    return np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float64) / 32768.0
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="ignore")[:300]
                last_err = RuntimeError(f"Key #{key_idx + 1} HTTP {exc.code}: {err_body}")
                if exc.code in (401, 402, 429, 500, 502, 503, 504):
                    continue
                raise last_err from exc
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
        time.sleep(min(8.0, 1.5 * (2**attempt)))

    raise RuntimeError(f"OpenRouter Gemini 3.8 TTS failed for {text!r}: {last_err}")


def apply_vocal_warmth(samples: np.ndarray) -> np.ndarray:
    """Apply zero-phase sub-bass cleanup and 10.6 kHz gentle low-pass preserving vocal air."""
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
    win = max(1, int(round(0.005 * RATE)))
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


def run_all() -> None:
    keys = discover_api_keys()
    print(f"Loaded {len(keys)} OpenRouter API key(s) cleanly.")

    data = load_script(FOLDER)
    global_style = (data.get("style") or {}).get("zh", "").strip()
    out_dir = FOLDER / "audio_zh"
    cache_dir = out_dir / ".cache_gemini38"
    cache_dir.mkdir(parents=True, exist_ok=True)

    lead_in_n = int(round(LEAD_IN * RATE))
    line_gap_n = int(round(LINE_GAP * RATE))
    scene_gap_n = int(round(SCENE_GAP * RATE))
    tail_n = int(round(TAIL * RATE))

    cursor = lead_in_n
    merged_chunks = [np.zeros(lead_in_n, dtype=np.float64)]
    tl = {
        "lang": "zh",
        "voice": f"{MODEL} ({VOICE})",
        "rate": "1.0",
        "lead_in": LEAD_IN,
        "line_gap": LINE_GAP,
        "gap": SCENE_GAP,
        "tail": TAIL,
        "scenes": [],
    }

    scenes = data["scenes"]
    for sc_idx, sc in enumerate(scenes):
        sc_id = sc["id"]
        scene_dir = (sc.get("dir") or {}).get("zh", "").strip()
        instructions = f"{global_style} {scene_dir}".strip()
        sc_start_sample = cursor
        sc_chunks: list[np.ndarray] = []
        line_entries: list[dict] = []

        lines = sc["zh"]
        for ln_idx, line in enumerate(lines):
            spoken = say(line)
            caption = show(line)
            print(f"-> [{sc_id} #{ln_idx + 1}] {spoken}")
            raw = synthesize_line(spoken, instructions, keys, cache_dir)
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
        print(f"  ok {sc_id}.wav ({sc_dur_s:.3f}s, {len(lines)} lines)")

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

    print(f"\nBuilt {nar_path.name}, {tl_path.name} & {tl_js_path.name} -- total duration: {tl['total']:.3f}s")
    for sc in tl["scenes"]:
        print(f"  {sc['id']}: start={sc['start']:.3f}s dur={sc['dur']:.3f}s ({len(sc['lines'])} lines)")


if __name__ == "__main__":
    run_all()
