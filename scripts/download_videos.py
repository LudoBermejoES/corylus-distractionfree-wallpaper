#!/usr/bin/env python3
"""Fetch stock video clips from Pexels + Pixabay and download into videos/<category>/ as .mp4.

Run transcode_videos.py afterward to convert the downloaded files to WebM.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEOS_DIR = os.path.join(ROOT, "videos")
MANIFEST_PATH = os.path.join(VIDEOS_DIR, "MANIFEST.json")

CATEGORIES = {
    "nature": "nature landscape seamless loop",
    "space": "space nebula stars loop",
    "sci-fi-cyberpunk": "cyberpunk neon city seamless loop",
    "fantasy": "fantasy magical forest loop",
    "city-architecture": "city skyline architecture timelapse loop",
    "abstract": "abstract background seamless loop",
    "vehicles": "car driving road loop",
    "animals": "wildlife animals loop",
    "minimal": "minimal simple background loop",
    "dark-night": "night dark ambience seamless loop",
    "art-other": "artistic creative background loop",
}

PEXELS_PER_CATEGORY = 30
PEXELS_BATCH_SIZE = 10
PIXABAY_PER_CATEGORY = 20

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def load_env():
    env_path = os.path.join(ROOT, ".env")
    env = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def http_get_json(url, headers=None):
    merged = {"User-Agent": USER_AGENT}
    merged.update(headers or {})
    req = urllib.request.Request(url, headers=merged)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_file(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


def pexels_search(api_key, query, page, per_page=10):
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "per_page": per_page, "page": page}
    )
    return http_get_json(url, headers={"Authorization": api_key})


def pexels_best_file(video):
    files = video.get("video_files", [])
    files = [
        f for f in files
        if f.get("file_type") == "video/mp4"
        and (f.get("width") or 0) >= (f.get("height") or 0)
    ]
    if not files:
        return None
    return max(files, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))


def pixabay_search(api_key, query, page, per_page=50):
    url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
        {"key": api_key, "q": query, "per_page": per_page, "page": page}
    )
    return http_get_json(url)


def pixabay_best_file(hit):
    videos = hit.get("videos", {})
    for quality in ("large", "medium", "small", "tiny"):
        v = videos.get(quality)
        if v and (v.get("width") or 0) >= (v.get("height") or 0):
            return v
    return None


def fetch_pexels(api_key, manifest, seen_ids):
    print("\n=== Pexels: fetching in round-robin batches of 10 ===", flush=True)
    cat_names = list(CATEGORIES.keys())
    collected = {c: [] for c in cat_names}
    pages = {c: 1 for c in cat_names}
    done = set()

    while len(done) < len(cat_names):
        for cat in cat_names:
            if cat in done:
                continue
            query = CATEGORIES[cat]
            needed = PEXELS_PER_CATEGORY - len(collected[cat])
            if needed <= 0:
                done.add(cat)
                continue
            print(f"  [pexels/{cat}] page {pages[cat]}, need {needed} more...", flush=True)
            try:
                data = pexels_search(api_key, query, pages[cat], per_page=PEXELS_BATCH_SIZE)
            except Exception as e:
                print(f"    ERROR: {e}", flush=True)
                done.add(cat)
                continue
            videos = data.get("videos", [])
            if not videos:
                print(f"    no more results for {cat}", flush=True)
                done.add(cat)
                continue
            for v in videos:
                if len(collected[cat]) >= PEXELS_PER_CATEGORY:
                    break
                vid = f"pexels-{v['id']}"
                if vid in seen_ids:
                    continue
                best = pexels_best_file(v)
                if not best:
                    continue
                seen_ids.add(vid)
                collected[cat].append({
                    "source": "pexels",
                    "id": v["id"],
                    "category": cat,
                    "download_url": best["link"],
                    "width": best.get("width"),
                    "height": best.get("height"),
                    "author": v.get("user", {}).get("name"),
                    "author_url": v.get("user", {}).get("url"),
                    "page_url": v.get("url"),
                    "license": "Pexels License (free to use, no attribution required) - https://www.pexels.com/license/",
                })
            pages[cat] += 1
            time.sleep(0.3)
            if len(collected[cat]) >= PEXELS_PER_CATEGORY:
                done.add(cat)

    for cat, items in collected.items():
        manifest.setdefault(cat, []).extend(items)
    total = sum(len(v) for v in collected.values())
    print(f"Pexels total collected: {total}", flush=True)


def fetch_pixabay(api_key, manifest, seen_ids):
    print("\n=== Pixabay: fetching top-liked per category ===", flush=True)
    for cat, query in CATEGORIES.items():
        print(f"  [pixabay/{cat}] searching...", flush=True)
        all_hits = []
        for page in (1, 2):
            try:
                data = pixabay_search(api_key, query, page, per_page=50)
            except Exception as e:
                print(f"    ERROR: {e}", flush=True)
                break
            hits = data.get("hits", [])
            if not hits:
                break
            all_hits.extend(hits)
            time.sleep(0.3)
        all_hits.sort(key=lambda h: h.get("likes", 0), reverse=True)
        picked = []
        for h in all_hits:
            if len(picked) >= PIXABAY_PER_CATEGORY:
                break
            vid = f"pixabay-{h['id']}"
            if vid in seen_ids:
                continue
            best = pixabay_best_file(h)
            if not best:
                continue
            seen_ids.add(vid)
            picked.append({
                "source": "pixabay",
                "id": h["id"],
                "category": cat,
                "download_url": best["url"],
                "width": best.get("width"),
                "height": best.get("height"),
                "author": h.get("user"),
                "author_url": h.get("userURL"),
                "page_url": h.get("pageURL"),
                "likes": h.get("likes"),
                "views": h.get("views"),
                "license": "Pixabay Content License (free to use, no attribution required) - https://pixabay.com/service/license-summary/",
            })
        manifest.setdefault(cat, []).extend(picked)
        print(f"    picked {len(picked)} (from {len(all_hits)} results)", flush=True)


DOWNLOAD_WORKERS = 8


def _download_one(args):
    idx, total, cat, item = args
    name = f"{item['source']}-{item['id']}"
    cat_dir = os.path.join(VIDEOS_DIR, cat)
    mp4_path = os.path.join(cat_dir, f"{name}.mp4")
    if os.path.exists(mp4_path):
        print(f"  [{idx}/{total}] {cat}/{name} already downloaded, skipping", flush=True)
        return item, f"videos/{cat}/{name}.mp4"
    print(f"  [{idx}/{total}] {cat}/{name} downloading...", flush=True)
    try:
        download_file(item["download_url"], mp4_path)
    except Exception as e:
        print(f"  [{idx}/{total}] {cat}/{name} DOWNLOAD FAILED: {e}", flush=True)
        return item, None
    print(f"  [{idx}/{total}] {cat}/{name} done", flush=True)
    return item, f"videos/{cat}/{name}.mp4"


def download_all(manifest):
    print(f"\n=== Downloading source files (.mp4) with {DOWNLOAD_WORKERS} workers ===", flush=True)
    for cat in manifest:
        os.makedirs(os.path.join(VIDEOS_DIR, cat), exist_ok=True)

    flat = [(cat, item) for cat, items in manifest.items() for item in items]
    total = len(flat)
    tasks = [(i + 1, total, cat, item) for i, (cat, item) in enumerate(flat)]

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        for item, downloaded_file in pool.map(_download_one, tasks):
            item["downloaded_file"] = downloaded_file


def main():
    env = load_env()
    pexels_key = env.get("PEXELS_API_KEY")
    pixabay_key = env.get("PIXABAY_API_KEY")
    if not pexels_key or not pixabay_key:
        print("Missing API keys in .env", file=sys.stderr)
        sys.exit(1)

    os.makedirs(VIDEOS_DIR, exist_ok=True)
    manifest = {}
    seen_ids = set()

    fetch_pixabay(pixabay_key, manifest, seen_ids)
    fetch_pexels(pexels_key, manifest, seen_ids)

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest written to {MANIFEST_PATH} (metadata only, before download)", flush=True)

    download_all(manifest)

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nFinal manifest written to {MANIFEST_PATH}", flush=True)

    print("\n=== Summary ===", flush=True)
    for cat, items in manifest.items():
        ok = sum(1 for i in items if i.get("downloaded_file"))
        print(f"  {cat}: {ok}/{len(items)} downloaded", flush=True)

    print("\nRun transcode_videos.py next to convert these to WebM.", flush=True)


if __name__ == "__main__":
    main()
