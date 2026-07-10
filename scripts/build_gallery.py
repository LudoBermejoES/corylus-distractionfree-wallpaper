#!/usr/bin/env python3
"""Build the static gallery site: scan images/, videos/, animated/, generate
thumbnails + gallery-index.json into site/, ready to publish to GitHub Pages.

Usage: scripts/build_gallery.py [--repo owner/name] [--branch main]

The published site (site/) contains ONLY the front-end, generated thumbnails,
and the JSON index -- never the full-size media, which the front-end loads on
demand from raw.githubusercontent.com. This keeps the Pages deployment well
under GitHub's ~1 GB site limit even though the media itself is ~1.4 GB.
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DIR = os.path.join(ROOT, "site")
THUMBS_DIR = os.path.join(SITE_DIR, "thumbs")
INDEX_PATH = os.path.join(SITE_DIR, "gallery-index.json")
MANIFEST_PATH = os.path.join(ROOT, "videos", "MANIFEST.json")

MEDIA_DIRS = [
    ("images", "image", (".webp",)),
    ("videos", "video", (".webm",)),
    ("animated", "animated", (".webp",)),
]

DEFAULT_REPO = "LudoBermejoES/corylus-distractionfree-wallpaper"
DEFAULT_BRANCH = "main"
THUMB_WIDTH = 480
PREVIEW_CLIP_SECONDS = 3


def raw_url(repo, branch, rel_path):
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel_path}"


def load_video_credits():
    """Map filename stem -> credit dict, from videos/MANIFEST.json.

    Not every video file has a manifest entry (some predate this repo's
    download scripts, inherited from the upstream wallpaper fork) -- callers
    must treat a miss as "no credit available", not an error.
    """
    if not os.path.isfile(MANIFEST_PATH):
        return {}
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)
    by_stem = {}
    for entries in manifest.values():
        for e in entries:
            downloaded = e.get("downloaded_file")
            if not downloaded:
                continue
            stem = os.path.splitext(os.path.basename(downloaded))[0]
            by_stem[stem] = {
                "author": e.get("author"),
                "authorUrl": e.get("author_url"),
                "license": e.get("license"),
                "source": e.get("source"),
                "pageUrl": e.get("page_url"),
            }
    return by_stem


def find_media_files():
    """Yield (kind, category, rel_path, abs_path) for every media file."""
    for dirname, kind, extensions in MEDIA_DIRS:
        base = os.path.join(ROOT, dirname)
        if not os.path.isdir(base):
            continue
        for cat in sorted(os.listdir(base)):
            cat_dir = os.path.join(base, cat)
            if not os.path.isdir(cat_dir):
                continue
            for fname in sorted(os.listdir(cat_dir)):
                if fname.lower().endswith(extensions):
                    rel = os.path.join(dirname, cat, fname)
                    yield kind, cat, rel, os.path.join(cat_dir, fname)


def thumb_rel_path(kind, category, filename):
    stem = os.path.splitext(filename)[0]
    # Videos get a short muted looping WebM preview clip instead of a static
    # poster, so grid tiles play motion (like a Pexels/Unsplash grid) rather
    # than showing a still frame. Image/animated thumbs are WebP stills,
    # generated via Pillow (no ffmpeg encoder dependency there).
    ext = "webm" if kind == "video" else "webp"
    return os.path.join(kind, category, f"{stem}.{ext}")


def thumb_is_fresh(src_abs, thumb_abs):
    if not os.path.isfile(thumb_abs):
        return False
    return os.path.getmtime(thumb_abs) >= os.path.getmtime(src_abs)


def _probe_duration(src_abs):
    """Return the source clip's duration in seconds, or None if unknown."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", src_abs,
        ],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def generate_video_preview(src_abs, thumb_abs):
    """Generate a short muted looping WebM (VP9) preview clip for a grid tile.

    Starts 1s in (skips a common black/fade-in first frame) unless the source
    is too short, in which case it starts from 0. Silent (-an) since previews
    autoplay -- audio would be unwanted/blocked by browsers anyway.
    """
    os.makedirs(os.path.dirname(thumb_abs), exist_ok=True)
    duration = _probe_duration(src_abs)
    start = "1" if duration is None or duration > PREVIEW_CLIP_SECONDS + 1 else "0"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", start, "-i", src_abs, "-t", str(PREVIEW_CLIP_SECONDS),
        "-vf", f"scale={THUMB_WIDTH}:-2",
        "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "36", "-cpu-used", "4",
        "-row-mt", "1", "-an",
        thumb_abs,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and start != "0":
        # Retry from the very start if seeking to 1s failed (very short clip).
        cmd[cmd.index("-ss") + 1] = "0"
        result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr


def generate_image_thumb(src_abs, thumb_abs):
    from PIL import Image

    os.makedirs(os.path.dirname(thumb_abs), exist_ok=True)
    try:
        with Image.open(src_abs) as im:
            if getattr(im, "is_animated", False):
                im.seek(0)
            im = im.convert("RGB")
            w, h = im.size
            new_h = max(1, round(h * THUMB_WIDTH / w))
            im = im.resize((THUMB_WIDTH, new_h))
            im.save(thumb_abs, "WEBP", quality=80)
        return True, ""
    except Exception as e:  # noqa: BLE001 -- report and let caller fail the build
        return False, str(e)


def build(repo, branch):
    credits = load_video_credits()
    items = []
    errors = []

    for kind, category, rel_path, abs_path in find_media_files():
        filename = os.path.basename(rel_path)
        thumb_rel = thumb_rel_path(kind, category, filename)
        thumb_abs = os.path.join(THUMBS_DIR, thumb_rel)

        if not thumb_is_fresh(abs_path, thumb_abs):
            if kind == "video":
                ok, err = generate_video_preview(abs_path, thumb_abs)
            else:
                ok, err = generate_image_thumb(abs_path, thumb_abs)
            if not ok:
                errors.append(f"{rel_path}: {err.strip()}")
                continue

        item = {
            "kind": kind,
            "category": category,
            "filename": filename,
            "rawUrl": raw_url(repo, branch, rel_path.replace(os.sep, "/")),
            "thumbUrl": f"thumbs/{thumb_rel.replace(os.sep, '/')}",
        }

        if kind == "video":
            stem = os.path.splitext(filename)[0]
            credit = credits.get(stem)
            if credit:
                item["credit"] = {k: v for k, v in credit.items() if v}

        items.append(item)

    if errors:
        print("Thumbnail generation failed for:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return items, errors

    return items, []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    args = parser.parse_args()

    os.makedirs(SITE_DIR, exist_ok=True)
    items, errors = build(args.repo, args.branch)

    if not items:
        print("ERROR: gallery index is empty -- no media found.", file=sys.stderr)
        sys.exit(1)
    if errors:
        print(f"ERROR: {len(errors)} item(s) missing a thumbnail.", file=sys.stderr)
        sys.exit(1)

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)

    by_category = {}
    for item in items:
        by_category.setdefault((item["kind"], item["category"]), 0)
        by_category[(item["kind"], item["category"])] += 1

    print(f"Wrote {INDEX_PATH} with {len(items)} items:")
    for (kind, category), count in sorted(by_category.items()):
        print(f"  {kind}/{category}: {count}")


if __name__ == "__main__":
    main()
