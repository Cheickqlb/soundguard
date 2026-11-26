"""
SoundGuard - dataset preparation for Edge Impulse
--------------------------------------------------
Builds 3 classes from the downloaded datasets:
    gunshot    <- UrbanSound8K (class "gun_shot")
    scream     <- Human Screaming Detection Dataset (Kaggle, "Screaming" folder)
    background <- UrbanSound8K (other classes) + ESC-50 + non-screaming clips

Every clip is converted to 16 kHz, mono, 16-bit WAV (same as the INMP441 mic),
cut to max 5 s, and named  <label>.<source>_<id>.wav  so that Edge Impulse can
read the label from the file name.

HOW TO USE
1. pip install librosa soundfile pandas
2. Unzip the 3 zip files into ONE folder, e.g.  C:\\soundguard\\data
      data\\UrbanSound8K\\...
      data\\ESC-50-master\\...
      data\\Human-Screaming-Detection-Dataset\\...
   (folder names don't need to be exact - the script searches inside)
3. Change DATA_DIR below if needed, then run:   python prepare_dataset.py
4. Result: a folder "edge_impulse_upload" with 3 subfolders.
"""

import os
import random
from collections import Counter

import librosa
import numpy as np
import pandas as pd
import soundfile as sf

# ===================== SETTINGS (change if needed) =====================
DATA_DIR = r"data"                       # folder containing the 3 unzipped datasets
OUT_DIR = r"edge_impulse_upload"          # output folder for Edge Impulse

SAMPLE_RATE = 16000      # Hz, same as the microphone on the ESP32-S3
MAX_SECONDS = 5.0        # longer clips are cut
MIN_SECONDS = 1.0        # shorter clips are padded with silence

MAX_GUNSHOT = 500        # UrbanSound8K has ~374 gunshots, all are used
MAX_SCREAM = 500
MAX_BG_US8K = 250        # background from UrbanSound8K
MAX_BG_ESC50 = 200       # background from ESC-50
MAX_BG_NOTSCREAM = 150   # background from the non-screaming folder

# ESC-50 categories left out of "background" because they sound too close to
# our target classes (mention this choice in the report / limitations)
ESC50_EXCLUDE = {"fireworks", "crying_baby", "glass_breaking"}

AUDIO_EXT = (".wav", ".flac", ".ogg", ".mp3")
random.seed(42)
# =======================================================================


def find_file(root, name):
    for dirpath, _, files in os.walk(root):
        if name in files:
            return os.path.join(dirpath, name)
    return None


def index_files(root):
    """filename -> full path, for every audio file under root"""
    idx = {}
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith(AUDIO_EXT):
                idx[f] = os.path.join(dirpath, f)
    return idx


def convert(src, label, tag, counter):
    try:
        y, _ = librosa.load(src, sr=SAMPLE_RATE, mono=True, duration=MAX_SECONDS)
    except Exception as e:
        print(f"  skipped (cannot read): {os.path.basename(src)} -> {e}")
        return
    if len(y) == 0 or np.max(np.abs(y)) < 1e-4:
        return  # empty or silent file
    min_len = int(MIN_SECONDS * SAMPLE_RATE)
    if len(y) < min_len:
        y = np.pad(y, (0, min_len - len(y)))
    y = y / max(np.max(np.abs(y)), 1e-6) * 0.9  # normalise volume
    os.makedirs(os.path.join(OUT_DIR, label), exist_ok=True)
    name = f"{label}.{tag}_{counter[label]:04d}.wav"
    sf.write(os.path.join(OUT_DIR, label, name), y, SAMPLE_RATE, subtype="PCM_16")
    counter[label] += 1


def sample(items, n):
    items = list(items)
    random.shuffle(items)
    return items[:n]


def main():
    counter = Counter()

    # ---------- UrbanSound8K ----------
    csv = find_file(DATA_DIR, "UrbanSound8K.csv")
    if csv is None:
        print("!! UrbanSound8K.csv not found - check DATA_DIR")
    else:
        print("UrbanSound8K ...")
        meta = pd.read_csv(csv)
        us_root = os.path.dirname(os.path.dirname(csv))  # dataset root
        files = index_files(us_root)
        gun = meta[meta["class"] == "gun_shot"]["slice_file_name"]
        for f in sample(gun, MAX_GUNSHOT):
            if f in files:
                convert(files[f], "gunshot", "us8k", counter)
        # background: spread evenly over the other 9 classes
        others = meta[meta["class"] != "gun_shot"]
        per_class = MAX_BG_US8K // others["class"].nunique()
        for _, grp in others.groupby("class"):
            for f in sample(grp["slice_file_name"], per_class):
                if f in files:
                    convert(files[f], "background", "us8k", counter)

    # ---------- ESC-50 ----------
    csv = find_file(DATA_DIR, "esc50.csv")
    if csv is None:
        print("!! esc50.csv not found - check DATA_DIR")
    else:
        print("ESC-50 ...")
        meta = pd.read_csv(csv)
        meta = meta[~meta["category"].isin(ESC50_EXCLUDE)]
        files = index_files(os.path.dirname(os.path.dirname(csv)))
        per_cat = max(1, MAX_BG_ESC50 // meta["category"].nunique())
        for _, grp in meta.groupby("category"):
            for f in sample(grp["filename"], per_cat):
                if f in files:
                    convert(files[f], "background", "esc50", counter)

    # ---------- Human Screaming Detection Dataset ----------
    print("Screaming dataset ...")
    screams, not_screams = [], []
    for dirpath, _, fs in os.walk(DATA_DIR):
        low = dirpath.lower()
        if "urbansound" in low or "esc-50" in low:
            continue
        for f in fs:
            if not f.lower().endswith(AUDIO_EXT):
                continue
            p = os.path.join(dirpath, f)
            parts = low.replace("\\", "/").split("/")
            if any("not" in x and "scream" in x for x in parts):
                not_screams.append(p)
            elif any("scream" in x for x in parts):
                screams.append(p)
    if not screams:
        print("!! no scream files found - check the folder names")
    for p in sample(screams, MAX_SCREAM):
        convert(p, "scream", "hsd", counter)
    for p in sample(not_screams, MAX_BG_NOTSCREAM):
        convert(p, "background", "hsdneg", counter)

    print("\nDone. Clips per class:")
    for k, v in sorted(counter.items()):
        print(f"  {k:<11} {v}")
    print(f"\nUpload folder: {OUT_DIR}")


if __name__ == "__main__":
    main()
