#!/usr/bin/env python3
"""Download N landscape video clips for a single search query from Pexels + Pixabay.

Usage: python3 scripts/download_single_query.py "<query>" <count> <output_dir>

Splits count evenly across both sources, dedupes by source+id, skips portrait
clips. Downloads raw .mp4 only -- run transcode_videos.py afterward.
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def pixabay_best_file(hit):
    videos = hit.get("videos", {})
    for quality in ("large", "medium", "small", "tiny"):
        v = videos.get(quality)
        if v and (v.get("width") or 0) >= (v.get("height") or 0):
            return v
    return None


def fetch_pexels(api_key, query, want):
    print(f"[pexels] searching \"{query}\"...", flush=True)
    picked = []
    page = 1
    while len(picked) < want:
        url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
            {"query": query, "per_page": 15, "page": page}
        )
        try:
            data = http_get_json(url, headers={"Authorization": api_key})
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)
            break
        videos = data.get("videos", [])
        if not videos:
            break
        for v in videos:
            if len(picked) >= want:
                break
            best = pexels_best_file(v)
            if not best:
                continue
            picked.append({
                "source": "pexels",
                "id": v["id"],
                "download_url": best["link"],
                "width": best.get("width"),
                "height": best.get("height"),
                "author": v.get("user", {}).get("name"),
                "author_url": v.get("user", {}).get("url"),
                "page_url": v.get("url"),
                "license": "Pexels License (free to use, no attribution required) - https://www.pexels.com/license/",
            })
        page += 1
    print(f"  picked {len(picked)}", flush=True)
    return picked


def fetch_pixabay(api_key, query, want):
    print(f"[pixabay] searching \"{query}\"...", flush=True)
    all_hits = []
    for page in (1, 2, 3):
        url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
            {"key": api_key, "q": query, "per_page": 50, "page": page}
        )
        try:
            data = http_get_json(url)
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)
            break
        hits = data.get("hits", [])
        if not hits:
            break
        all_hits.extend(hits)
    all_hits.sort(key=lambda h: h.get("likes", 0), reverse=True)
    picked = []
    for h in all_hits:
        if len(picked) >= want:
            break
        best = pixabay_best_file(h)
        if not best:
            continue
        picked.append({
            "source": "pixabay",
            "id": h["id"],
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
    print(f"  picked {len(picked)} (from {len(all_hits)} results)", flush=True)
    return picked


def _download_one(args):
    idx, total, out_dir, item = args
    name = f"{item['source']}-{item['id']}"
    dest = os.path.join(out_dir, f"{name}.mp4")
    if os.path.exists(dest):
        print(f"  [{idx}/{total}] {name} already downloaded, skipping", flush=True)
        return item, dest
    print(f"  [{idx}/{total}] {name} downloading...", flush=True)
    try:
        download_file(item["download_url"], dest)
    except Exception as e:
        print(f"  [{idx}/{total}] {name} DOWNLOAD FAILED: {e}", flush=True)
        return item, None
    print(f"  [{idx}/{total}] {name} done", flush=True)
    return item, dest


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} \"<query>\" <count> <output_dir>", file=sys.stderr)
        sys.exit(1)
    query = sys.argv[1]
    count = int(sys.argv[2])
    out_dir = sys.argv[3]
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(ROOT, out_dir)
    os.makedirs(out_dir, exist_ok=True)

    env = load_env()
    pexels_key = env.get("PEXELS_API_KEY")
    pixabay_key = env.get("PIXABAY_API_KEY")
    if not pexels_key or not pixabay_key:
        print("Missing API keys in .env", file=sys.stderr)
        sys.exit(1)

    half = (count + 1) // 2
    items = fetch_pixabay(pixabay_key, query, half)
    items += fetch_pexels(pexels_key, query, count - len(items))

    seen = set()
    deduped = []
    for it in items:
        key = (it["source"], it["id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    items = deduped[:count]

    print(f"\nTotal picked: {len(items)}", flush=True)
    print(f"Downloading to {out_dir} with 6 workers...\n", flush=True)

    tasks = [(i + 1, len(items), out_dir, it) for i, it in enumerate(items)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_download_one, tasks))

    manifest_path = os.path.join(out_dir, "MANIFEST.json")
    manifest = []
    ok = 0
    for item, dest in results:
        item["downloaded_file"] = dest
        if dest:
            ok += 1
        manifest.append(item)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nDone: {ok}/{len(items)} downloaded. Manifest at {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
