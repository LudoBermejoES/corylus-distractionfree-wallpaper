#!/usr/bin/env python3
"""Build the static gallery site: scan images/, videos/, animated/, generate
thumbnails + gallery-index.json into site/, ready to publish to GitHub Pages.

Usage: scripts/build_gallery.py [--repo owner/name] [--branch main]

CI passes --branch "$GITHUB_SHA" so every rawUrl is pinned to the commit the
site was built from: Corylus checks each download against the sha256 in this
index, and a pinned URL never serves different bytes later.

The published site (site/) contains ONLY the front-end, generated thumbnails,
and the JSON index -- never the full-size media, which the front-end loads on
demand from raw.githubusercontent.com. This keeps the Pages deployment well
under GitHub's ~1 GB site limit even though the media itself is ~1.4 GB.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DIR = os.path.join(ROOT, "site")
THUMBS_DIR = os.path.join(SITE_DIR, "thumbs")
INDEX_PATH = os.path.join(SITE_DIR, "gallery-index.json")
MANIFEST_PATH = os.path.join(ROOT, "videos", "MANIFEST.json")

# .mp4 is listed alongside .webm because VP9 is not always the smaller of the
# two: a clip that is mostly fine moving detail (rain, snow, noise) can come out
# several times larger as webm than the h264 source it was made from, and for
# those we keep the mp4 instead. Corylus plays both (webm, ogg and mp4).
MEDIA_DIRS = [
    ("images", "image", (".webp",)),
    ("videos", "video", (".webm", ".mp4")),
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
                "description": e.get("description"),
            }
    return by_stem


def title_for(filename, description):
    """Human label for a tile: the manifest description, else the bare stem.

    Most of the collection is inherited from the upstream wallpaper fork and
    has no description, so the stem is all there is -- still better than an
    unlabelled thumbnail when you are trying to tell two clips apart.
    """
    if description:
        return description
    stem = os.path.splitext(filename)[0]
    return stem.replace("_", " ").replace("-", " ").strip()


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


CACHE_PATH = os.path.join(THUMBS_DIR, ".build-cache.json")


def load_git_blob_hashes():
    """Map repo-relative path -> git blob SHA, for every tracked file.

    Used (rather than mtime) to decide whether a thumbnail is stale: every CI
    run does a fresh `actions/checkout`, which stamps every file with the
    checkout's wall-clock time -- so comparing mtimes would always call every
    source file "newer" than a cached thumbnail, defeating any cache. A git
    blob hash only changes when the file's actual content changes, and
    `git ls-files -s` reads it straight from the index with no file I/O.
    """
    result = subprocess.run(
        ["git", "-C", ROOT, "ls-files", "-s"],
        capture_output=True, text=True,
    )
    hashes = {}
    if result.returncode != 0:
        return hashes  # not a git checkout (e.g. ad-hoc local run) -- fall back to "always rebuild"
    for line in result.stdout.splitlines():
        # "100644 <sha> 0\t<path>"
        meta, path = line.split("\t", 1)
        sha = meta.split()[1]
        hashes[path] = sha
    return hashes


def load_build_cache():
    if not os.path.isfile(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_build_cache(cache):
    os.makedirs(THUMBS_DIR, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f)


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


# Must match the id rule in Corylus (src-tauri/app/src/commands/deep_link.rs).
ID_RE = re.compile(r"^(image|video|animated)/[a-z0-9-]{1,40}/[A-Za-z0-9_][A-Za-z0-9._-]{0,99}$")


def file_sha256(abs_path):
    h = hashlib.sha256()
    with open(abs_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_entry(value):
    """Cache values were a bare blob hash before sha256 was cached alongside."""
    return {"blob": value} if isinstance(value, str) else (value or {})


def build(repo, branch):
    credits = load_video_credits()
    blob_hashes = load_git_blob_hashes()
    old_cache = load_build_cache()
    new_cache = {}
    items = []
    errors = []
    regenerated = 0
    reused = 0

    for kind, category, rel_path, abs_path in find_media_files():
        filename = os.path.basename(rel_path)
        thumb_rel = thumb_rel_path(kind, category, filename)
        thumb_abs = os.path.join(THUMBS_DIR, thumb_rel)
        rel_key = rel_path.replace(os.sep, "/")

        current_hash = blob_hashes.get(rel_key)
        cached = cache_entry(old_cache.get(rel_key))
        cached_hash = cached.get("blob")
        is_fresh = (
            current_hash is not None
            and current_hash == cached_hash
            and os.path.isfile(thumb_abs)
        )

        if not is_fresh:
            if kind == "video":
                ok, err = generate_video_preview(abs_path, thumb_abs)
            else:
                ok, err = generate_image_thumb(abs_path, thumb_abs)
            if not ok:
                errors.append(f"{rel_path}: {err.strip()}")
                continue
            regenerated += 1
        else:
            reused += 1

        # Hashing ~1.6 GB on every push is slow; the sha256 only changes with the blob.
        if current_hash is not None and current_hash == cached_hash and cached.get("sha256"):
            sha256 = cached["sha256"]
        else:
            sha256 = file_sha256(abs_path)
        if current_hash is not None:
            new_cache[rel_key] = {"blob": current_hash, "sha256": sha256}

        stem = os.path.splitext(filename)[0]
        item = {
            "id": f"{kind}/{category}/{stem}",
            "kind": kind,
            "category": category,
            "filename": filename,
            "size": os.path.getsize(abs_path),
            "sha256": sha256,
            "rawUrl": raw_url(repo, branch, rel_key),
            "thumbUrl": f"thumbs/{thumb_rel.replace(os.sep, '/')}",
            # Only the Pexels/Pixabay downloads record one; null shows as
            # "Licence not recorded" in Corylus.
            "license": None,
        }

        description = None
        if kind == "video":
            credit = credits.get(stem)
            if credit:
                description = credit.get("description")
                item["license"] = credit.get("license")
                item["credit"] = {
                    k: v for k, v in credit.items() if v and k not in ("description", "license")
                }
        item["title"] = title_for(filename, description)
        if description:
            item["description"] = description

        items.append(item)

    print(f"Thumbnails: {regenerated} generated, {reused} reused from cache.")
    save_build_cache(new_cache)

    if errors:
        print("Thumbnail generation failed for:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return items, errors

    return items, []


def validate_items(items):
    """Errors that must stop the build: Corylus refuses such items anyway."""
    problems = []
    seen = set()
    for item in items:
        iid = item.get("id", "")
        if not ID_RE.match(iid) or ".." in iid:
            problems.append(f"bad id: {iid!r}")
        if iid in seen:
            problems.append(f"duplicate id: {iid}")
        seen.add(iid)
        if not isinstance(item.get("size"), int) or item["size"] <= 0:
            problems.append(f"{iid}: missing size")
        if not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256") or ""):
            problems.append(f"{iid}: missing sha256")
        if "license" not in item:
            problems.append(f"{iid}: missing license")
    return problems


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
    problems = validate_items(items)
    if problems:
        print("ERROR: the index would publish invalid items:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
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
