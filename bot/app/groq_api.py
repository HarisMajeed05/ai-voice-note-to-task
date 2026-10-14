"""Thin client for the Groq OpenAI-compatible API (chat and speech-to-text)."""
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from . import config


def _headers():
    return {"Authorization": f"Bearer {config.GROQ_API_KEY}"}


def chat(messages, json_mode=True):
    """Returns the assistant text. Retries on rate limits."""
    body = {
        "model": config.GROQ_LLM_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_completion_tokens": 4096,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    for _ in range(3):
        resp = requests.post(
            f"{config.GROQ_BASE_URL}/chat/completions",
            headers=_headers(), json=body, timeout=120,
        )
        if resp.status_code == 429:
            time.sleep(min(float(resp.headers.get("retry-after", 5)), 30))
            continue
        if resp.status_code == 400 and "response_format" in body:
            del body["response_format"]
            continue
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        text = resp.json()["choices"][0]["message"]["content"] or ""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    raise RuntimeError("Groq chat failed after retries")


def _to_flac(raw):
    """Converts audio to 16 kHz mono FLAC. Returns None when ffmpeg is missing or fails."""
    if not shutil.which("ffmpeg"):
        return None
    tmp = Path(tempfile.mkdtemp())
    try:
        src, dst = tmp / "in.bin", tmp / "out.flac"
        src.write_bytes(raw)
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "16000", str(dst)],
            timeout=120, check=False,
        )
        return dst.read_bytes() if dst.exists() and dst.stat().st_size else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _transcribe_once(filename, raw):
    data = {"model": config.GROQ_STT_MODEL, "response_format": "json"}
    if config.LANGUAGE:
        data["language"] = config.LANGUAGE
    for _ in range(3):
        resp = requests.post(
            f"{config.GROQ_BASE_URL}/audio/transcriptions",
            headers=_headers(), files={"file": (filename, raw)}, data=data, timeout=180,
        )
        if resp.status_code == 429:
            time.sleep(min(float(resp.headers.get("retry-after", 5)), 30))
            continue
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return (resp.json().get("text") or "").strip()
    raise RuntimeError("Groq transcription rate limited")


def transcribe(filename, raw):
    """Speech to text. Falls back to FLAC conversion if the original format is rejected."""
    try:
        return _transcribe_once(filename, raw)
    except RuntimeError as first_error:
        flac = _to_flac(raw)
        if flac is None:
            raise first_error
        return _transcribe_once("voice.flac", flac)
