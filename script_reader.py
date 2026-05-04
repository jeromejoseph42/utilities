"""
script_reader.py
================
Paste your script to clipboard, run this, record unique words,
then auto-stitch into a ≥ target-duration audio file.

Requirements:
    pip install pyperclip sounddevice soundfile numpy pydub
    # pydub also needs ffmpeg installed for mp3 export
"""

import re
import os
import time
import random
import threading
import shutil
from datetime import datetime
from pathlib import Path

import pyperclip
import numpy as np
import sounddevice as sd
import soundfile as sf

# ─── CONFIG ────────────────────────────────────────────────────

TARGET_MINUTES   = 15          # minimum output duration
SAMPLE_RATE      = 44100       # Hz
CHANNELS         = 1           # mono
RECORD_SECONDS   = 4           # max seconds per word recording (trims silence)
CONTEXT_WINDOW   = 2           # words left/right shown for intonation context

# Gap between words in the final output (seconds)
BASE_GAP         = 0.2        # base silence between words
RANDOM_GAP       = 0.05        # ± random jitter added to each gap (0 = no jitter)

# Where to save this session's recordings (auto-named by timestamp)
SESSION_DIR = Path("recordings/words")

OUTPUT_FILE      = Path("recordings/output.mp3")

# ─── NUMBER HANDLER ──────────────────────────────────────────────

def expand_numbers(text: str) -> str:
    """
    Convert numbers and units to Malay spoken form.
    10% -> 10 peratus
    RM5000 -> 5000 ringgit
    2.5 -> dua perpuluhan lima
    123 -> seratus dua puluh tiga
    """
    # Currency: RM (Ringgit Malaysia)
    text = re.sub(r'RM(\d+(?:\.\d+)?)', lambda m: f"{expand_number(m.group(1))} ringgit", text)
    
    # Percentage
    text = re.sub(r'(\d+(?:\.\d+)?)%', lambda m: f"{expand_number(m.group(1))} peratus", text)
    
    # Decimal numbers (must come before integers to avoid splitting)
    text = re.sub(r'(\d+)\.(\d+)', lambda m: f"{expand_number(m.group(1))} perpuluhan {expand_digits(m.group(2))}", text)
    
    # Standalone integers (word boundaries to avoid matching inside other numbers)
    text = re.sub(r'\b(\d+(?:,\d{3})*)\b', lambda m: expand_number(m.group(1).replace(',', '')), text)
    
    return text

def expand_digits(digits: str) -> str:
    """Expand digits individually (for decimal places)."""
    digit_map = {
        '0': 'sifar', '1': 'satu', '2': 'dua', '3': 'tiga', '4': 'empat',
        '5': 'lima', '6': 'enam', '7': 'tujuh', '8': 'lapan', '9': 'sembilan'
    }
    return ' '.join(digit_map[d] for d in digits)

def expand_number(num_str: str) -> str:
    """
    Convert number string to Malay words.
    Supports 0-999,999 (can be extended)
    """
    num = int(num_str)
    if num == 0:
        return "sifar"
    
    # Units
    units = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "lapan", "sembilan"]
    teens = ["sepuluh", "sebelas", "dua belas", "tiga belas", "empat belas", 
             "lima belas", "enam belas", "tujuh belas", "lapan belas", "sembilan belas"]
    tens = ["", "", "dua puluh", "tiga puluh", "empat puluh", "lima puluh", 
            "enam puluh", "tujuh puluh", "lapan puluh", "sembilan puluh"]
    
    if num < 10:
        return units[num]
    elif 10 <= num < 20:
        return teens[num - 10]
    elif 20 <= num < 100:
        t = num // 10
        u = num % 10
        if u == 0:
            return tens[t]
        return f"{tens[t]} {units[u]}"
    elif 100 <= num < 1000:
        h = num // 100
        remainder = num % 100
        if h == 1:
            prefix = "seratus"
        else:
            prefix = f"{units[h]} ratus"
        if remainder == 0:
            return prefix
        return f"{prefix} {expand_number(str(remainder))}"
    elif 1000 <= num < 1000000:
        th = num // 1000
        remainder = num % 1000
        if th == 1:
            prefix = "seribu"
        else:
            prefix = f"{expand_number(str(th))} ribu"
        if remainder == 0:
            return prefix
        return f"{prefix} {expand_number(str(remainder))}"
    
    # Fallback for very large numbers
    return num_str

# ─── TOKENISER ──────────────────────────────────────────────────────────────

def tokenise(text: str) -> list[str]:
    """
    Split text into word tokens.
    Hyphenated words (e.g. undang-undang) count as ONE token.
    Returns lowercase unique words preserving original order of first occurrence.
    """
    # FIRST: expand numbers in the text
    text = expand_numbers(text)
    
    # Normalise whitespace / line breaks
    text = re.sub(r'\s+', ' ', text.strip())
    # Match hyphenated-words OR plain words (no punctuation)
    raw_tokens = re.findall(r'\b[a-zA-Z]+(?:-[a-zA-Z]+)*\b', text)
    return raw_tokens


def unique_ordered(tokens: list[str]) -> list[str]:
    """Return unique tokens in first-occurrence order (case-insensitive)."""
    seen = set()
    result = []
    for t in tokens:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def get_context(tokens: list[str], idx: int, window: int = CONTEXT_WINDOW) -> str:
    """Return a short context string showing surrounding words."""
    start = max(0, idx - window)
    end   = min(len(tokens), idx + window + 1)
    parts = []
    for i in range(start, end):
        if i == idx:
            parts.append(f"[{tokens[i].upper()}]")
        else:
            parts.append(tokens[i])
    return " ".join(parts)

# ─── AUDIO HELPERS ──────────────────────────────────────────────────────────

def record_word(word: str, seconds: float = RECORD_SECONDS) -> np.ndarray:
    print(f"  ● Recording... (press Enter to stop)")
    start = time.time()
    audio = sd.rec(
        int(seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32"
    )
    input()
    sd.stop()
    elapsed = min(time.time() - start, seconds)
    samples = int(elapsed * SAMPLE_RATE)
    return audio[:samples].flatten()


def trim_silence(audio: np.ndarray, threshold: float = 0.01) -> np.ndarray:
    """Strip leading/trailing silence below threshold amplitude."""
    mask = np.abs(audio) > threshold
    if not mask.any():
        return audio
    first = np.argmax(mask)
    last  = len(mask) - np.argmax(mask[::-1])
    # Add 50ms padding so we don't clip the word
    pad = int(0.20 * SAMPLE_RATE)
    first = max(0, first - pad)
    last  = min(len(audio), last + pad)
    return audio[first:last]


def play_audio(audio: np.ndarray):
    """Play back a numpy audio array."""
    sd.play(audio, samplerate=SAMPLE_RATE)
    sd.wait()


def silence(seconds: float) -> np.ndarray:
    """Return a silent numpy array of given duration."""
    return np.zeros(int(seconds * SAMPLE_RATE), dtype="float32")


def audio_duration(audio: np.ndarray) -> float:
    """Duration in seconds."""
    return len(audio) / SAMPLE_RATE


def save_wav(path: Path, audio: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, SAMPLE_RATE)


def load_wav(path: Path) -> np.ndarray:
    audio, _ = sf.read(str(path), dtype="float32")
    return audio.flatten()

# ─── RECORDING PHASE ────────────────────────────────────────────────────────

def record_phase(all_tokens: list[str], words_to_record: list[str]) -> dict[str, Path]:
    """
    Prompt user to record each unique word.
    Returns dict: lowercase_word -> Path to saved .wav
    """
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    recordings: dict[str, Path] = {}

    # Build a lookup: word -> list of token indices (for context)
    token_lower = [t.lower() for t in all_tokens]

    print(f"\n{'─'*55}")
    print(f"  {len(words_to_record)} unique word(s) to record")
    print(f"  Session folder: {SESSION_DIR}")
    print(f"{'─'*55}")
    print("  Controls:  Enter = record   P = play back   R = redo   S = skip")
    print(f"{'─'*55}\n")

    for n, word in enumerate(words_to_record, 1):
        key = word.lower()

        # Find first occurrence for context
        try:
            idx = token_lower.index(key)
        except ValueError:
            idx = 0
        context = get_context(all_tokens, idx)

        print(f"[{n}/{len(words_to_record)}]  Word: \033[1m{word}\033[0m")
        print(f"           Context: {context}\n")

        audio = None
        while True:
            cmd = input("  → ").strip().lower()

            if cmd == "r" or (cmd == "" and audio is None):
                audio = record_word(word)
                audio = trim_silence(audio)
                dur = audio_duration(audio)
                
                print(f"  ✔ Recorded {dur:.2f}s  (P to play, Enter to keep, R to redo)\n")
                play_audio(audio)

            elif cmd == "p":
                if audio is not None:
                    print("  ▶ Playing...")
                    play_audio(audio)
                else:
                    print("  Nothing recorded yet — press Enter to record.\n")

            elif cmd == "s":
                print("  Skipped.\n")
                break

            elif cmd == "" and audio is not None:
                # Keep the recording
                path = SESSION_DIR / f"{key}.wav"
                save_wav(path, audio)
                recordings[key] = path
                print()
                break

            else:
                print("  Enter=record  P=play  R=redo  S=skip\n")

    return recordings

# ─── GENERATE PHASE ─────────────────────────────────────────────────────────

def build_audio(all_tokens: list[str], recordings: dict[str, Path],
                base_gap: float = BASE_GAP,
                random_gap: float = RANDOM_GAP) -> np.ndarray:
    """
    Stitch recordings into a single audio array using all_tokens as the script order.
    Words with no recording are silently skipped.
    """
    parts = []
    for token in all_tokens:
        key = token.lower()
        if key in recordings:
            word_audio = load_wav(recordings[key])
            parts.append(word_audio)
            gap = base_gap + random.uniform(-random_gap, random_gap)
            gap = max(0.05, gap)   # never negative
            parts.append(silence(gap))
    if not parts:
        return silence(1.0)
    return np.concatenate(parts)


def estimate_duration(all_tokens: list[str], recordings: dict[str, Path],
                      base_gap: float, random_gap: float) -> float:
    """Estimate total duration without fully building the array."""
    total = 0.0
    for token in all_tokens:
        key = token.lower()
        if key in recordings:
            # Load just to get length — cheap for small files
            a = load_wav(recordings[key])
            total += audio_duration(a)
            total += base_gap   # use base for estimate (jitter averages out)
    return total

# ─── GAP SETTINGS UI ────────────────────────────────────────────────────────

def configure_gaps() -> tuple[float, float]:
    print(f"\n{'─'*55}")
    print("  Gap settings")
    print(f"  Defaults: base={BASE_GAP}s  jitter=±{RANDOM_GAP}s")
    print(f"{'─'*55}")
    try:
        raw = input(f"  Base gap in seconds [{BASE_GAP}]: ").strip()
        base = float(raw) if raw else BASE_GAP
    except ValueError:
        base = BASE_GAP
    try:
        raw = input(f"  Random jitter ± seconds [{RANDOM_GAP}]: ").strip()
        jitter = float(raw) if raw else RANDOM_GAP
    except ValueError:
        jitter = RANDOM_GAP
    print(f"  Using base={base}s  jitter=±{jitter}s\n")
    return base, jitter

# ─── MAIN ───────────────────────────────────────────────────────────────────

def main():
    start_time = time.time()
    print("\n╔══════════════════════════════════════════════╗")
    print("║         Script Reader — Audio Builder        ║")
    print("╚══════════════════════════════════════════════╝\n")

    # ── Step 1: Get script from clipboard ──
    text = pyperclip.paste().strip()
    if not text:
        print("✘ Clipboard is empty. Copy your script first, then re-run.\n")
        return

    all_tokens = tokenise(text)
    unique_words = unique_ordered(all_tokens)

    print(f"  Script: {len(all_tokens)} total tokens, {len(unique_words)} unique words\n")

    # ── Step 2: Configure gaps ──
    base_gap, random_gap = configure_gaps()

    # ── Step 3: Load existing recordings, record only new words ──
    all_recordings: dict[str, Path] = {}
    recordings_root = Path("recordings/words")
    if recordings_root.exists():
        for wav in recordings_root.rglob("*.wav"):
            key = wav.stem.lower()
            if key not in all_recordings:
                all_recordings[key] = wav

    already = set(all_recordings.keys())
    unique_words = [w for w in unique_words if w.lower() not in already]
    reused = len(unique_ordered(all_tokens)) - len(unique_words)
    print(f"  ✔ {reused} reused from past sessions, {len(unique_words)} new to record\n")

    def do_record_phase(tokens, words):
        new_recs = record_phase(tokens, words)
        all_recordings.update(new_recs)

    if unique_words:
        do_record_phase(all_tokens, unique_words)
    else:
        print("  No new words to record — skipping to generate.\n")

    # ── Step 4: Duration check loop ──
    target_seconds = TARGET_MINUTES * 60

    while True:
        est = estimate_duration(all_tokens, all_recordings, base_gap, random_gap)
        est_min = est / 60

        print(f"\n{'─'*55}")
        print(f"  Estimated output duration: \033[1m{est_min:.1f} min\033[0m  (target: {TARGET_MINUTES} min)")

        if est >= target_seconds:
            print(f"  ✔ Target met!\n{'─'*55}")
            break
        else:
            shortage = (target_seconds - est) / 60
            print(f"  ✘ Short by ~{shortage:.1f} min. Add more text.\n{'─'*55}")
            print("  Copy additional paragraphs to clipboard, then press Enter.")
            print("  (Or type 'skip' to generate anyway)\n")
            cmd = input("  → ").strip().lower()
            if cmd == "skip":
                break

            extra_text = pyperclip.paste().strip()
            if not extra_text:
                print("  Clipboard still empty — nothing added.\n")
                continue

            # Append extra text, re-tokenise
            text += " " + extra_text
            all_tokens = tokenise(text)

            # Find newly unique words not yet recorded
            existing_keys = set(all_recordings.keys())
            all_unique_now = unique_ordered(all_tokens)
            new_words = [w for w in all_unique_now if w.lower() not in existing_keys]

            if new_words:
                print(f"\n  {len(new_words)} new word(s) to record from the extra text.")
                do_record_phase(all_tokens, new_words)
            else:
                print("  No new unique words in the added text.\n")

    # ── Step 5: Build, tweak gaps, and save ──
    while True:
        print(f"\n  Building audio...")
        final_audio = build_audio(all_tokens, all_recordings, base_gap, random_gap)
        actual_dur  = audio_duration(final_audio)
        print(f"  Duration: {actual_dur/60:.2f} min ({actual_dur:.1f}s)")

        name = input("  Save as (no extension, Enter to skip save): ").strip()
        if name:
            out_path = Path(f"recordings/{name}.mp3")
            save_wav(out_path, final_audio)
            print(f"  ✔ Saved: {out_path}")

        cmd = input("\n  Adjust gaps and rebuild? (Y / N): ").strip().lower()
        if cmd != "y":
            break
        base_gap, random_gap = configure_gaps()

    elapsed = time.time() - start_time
    mins, secs = divmod(int(elapsed), 60)
    saved = max(0, TARGET_MINUTES * 60 - int(elapsed))
    saved_m, saved_s = divmod(saved, 60)
    print(f"\n  Done! Time spent: {mins}m {secs}s — you saved {saved_m}m {saved_s}s vs reading it yourself!\n")


if __name__ == "__main__":
    main()