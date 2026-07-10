# Corylus Distraction-Free Wallpapers

Curated wallpaper and video collection used by [Corylus](https://github.com/LudoBermejoES/corylus) to offer background choices for its distraction-free writing mode.

## Origin

This repository is a fork of [mylinuxforwork/wallpaper](https://github.com/mylinuxforwork/wallpaper), the "ML4W Wallpaper Collection" — a personal wallpaper collection originally curated for tiling window managers. Corylus reuses that collection as a starting set of high-quality, distraction-free backgrounds, and adds/replaces images over time to fit its own use case.

## Why a separate repository

Corylus is a Tauri application; its main repository holds source code, not media. Bundling this collection there would bloat every clone and checkout with tens of megabytes of images that most contributors never need. Keeping it here instead lets Corylus:

- Reference this repo as a git submodule (`assets/distractionfree-wallpaper`) instead of committing binaries to the app repo's history.
- Download or update wallpapers independently of the app's release cycle.
- Diverge from upstream over time — adding, removing, or replacing images for distraction-free mode — without affecting the original collection.

## Structure

All media lives under [images/](images/), organized by category so Corylus can offer a curated picker instead of one flat list. A `videos/` folder will be added alongside it once video backgrounds are supported.

Animated backgrounds live separately under [animated/](animated/), mirroring the same category folder names — only the categories that currently have animated content exist there.

Some images fit more than one category and are duplicated across folders rather than forced into a single bucket.

All images are stored as WebP (lossy, quality 90) to keep the repository small without a visible quality loss. Animated backgrounds use animated WebP instead of GIF for smaller file sizes.

| Category | Description |
| --- | --- |
| `nature` | Landscapes, mountains, forests, seas, sunsets |
| `space` | Planets, nebulae, astronauts, spacecraft |
| `sci-fi-cyberpunk` | Futuristic tech, neon cityscapes, robots |
| `fantasy` | Surreal and imaginary scenes, alien worlds |
| `city-architecture` | Skylines, streets, buildings |
| `abstract` | Non-representational shapes, patterns, gradients |
| `anime` | Anime and manga-style art |
| `vehicles` | Cars, motorcycles, spacecraft in motion |
| `animals` | Wildlife and creatures |
| `minimal` | Simple, low-detail compositions |
| `dark-night` | Night scenes and dark/moody tones |
| `art-other` | Everything else that doesn't fit the categories above |

## Browsing the collection

A static gallery site (`site/`) lets you browse every image, video, and
animated background by category, preview it, and download it. It's built
automatically by [`.github/workflows/pages.yml`](.github/workflows/pages.yml)
on every push to `main` and published to **GitHub Pages**.

The published site itself is small (front-end + a generated JSON index +
small preview thumbnails/clips) — the full-size media is loaded on demand
from this repo's raw file URLs, not bundled into the Pages deployment. This
matters because the repo's media is well over Pages' ~1 GB site limit.

**One-time repo setup** (if Pages isn't already enabled): Settings → Pages →
Source → "GitHub Actions". After that, every push rebuilds and redeploys the
site automatically; the URL is shown in the workflow's `deploy` job summary
(typically `https://<owner>.github.io/<repo>/`).

To preview locally before pushing:

```
python3 scripts/build_gallery.py
python3 -m http.server --directory site 8000
# open http://localhost:8000/
```

`scripts/build_gallery.py` requires `ffmpeg` (with `libvpx-vp9` support, for
the short video preview clips) and the `Pillow` Python package (for image
thumbnails).

## Updating from upstream

The original collection is tracked as the `upstream` remote:

```
git fetch upstream
git merge upstream/main
```

## License

See [LICENSE](LICENSE).
