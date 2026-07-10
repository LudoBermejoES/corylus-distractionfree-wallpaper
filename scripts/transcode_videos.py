#!/usr/bin/env python3
"""Transcode downloaded .mp4 files under videos/<category>/ to .webm (VP9), then delete the .mp4.

Run download_videos.py first to populate the .mp4 source files.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEOS_DIR = os.path.join(ROOT, "videos")

# cpu-used 4 trades a little quality for a large (~5-10x) speedup vs the
# libvpx-vp9 default (0) -- default speed is impractical for batches of clips.
FFMPEG_CMD = [
    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", "{src}",
    "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "34",
    "-cpu-used", "4",
    "-row-mt", "1",
    "-an",
    "{dest}",
]


def find_mp4s():
    for cat in sorted(os.listdir(VIDEOS_DIR)):
        cat_dir = os.path.join(VIDEOS_DIR, cat)
        if not os.path.isdir(cat_dir):
            continue
        for fname in sorted(os.listdir(cat_dir)):
            if fname.lower().endswith(".mp4"):
                yield cat, os.path.join(cat_dir, fname)


def transcode(src_path, dest_path):
    cmd = [part.format(src=src_path, dest=dest_path) for part in FFMPEG_CMD]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr


def safe_remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def main():
    keep_mp4 = "--keep-mp4" in sys.argv
    items = list(find_mp4s())
    total = len(items)
    if total == 0:
        print("No .mp4 files found under videos/. Run download_videos.py first.")
        return

    print(f"Found {total} .mp4 files to transcode.\n", flush=True)
    ok_count = 0
    fail_count = 0
    skip_count = 0
    for i, (cat, mp4_path) in enumerate(items, 1):
        dest_path = mp4_path[:-4] + ".webm"
        base = os.path.basename(mp4_path)
        if os.path.exists(dest_path):
            print(f"[{i}/{total}] {cat}/{base} -> already transcoded, skipping", flush=True)
            if not keep_mp4:
                safe_remove(mp4_path)
            ok_count += 1
            continue
        if not os.path.exists(mp4_path):
            print(f"[{i}/{total}] {cat}/{base} -> source missing, skipping", flush=True)
            skip_count += 1
            continue
        print(f"[{i}/{total}] {cat}/{base} transcoding...", flush=True)
        ok, err = transcode(mp4_path, dest_path)
        if not ok:
            print(f"    FAILED: {err[-500:]}", flush=True)
            safe_remove(dest_path)  # remove partial/empty output on failure
            fail_count += 1
            continue
        if not keep_mp4:
            safe_remove(mp4_path)
        ok_count += 1

    print(f"\nDone. {ok_count} succeeded, {fail_count} failed, {skip_count} skipped (missing source).", flush=True)


if __name__ == "__main__":
    main()
