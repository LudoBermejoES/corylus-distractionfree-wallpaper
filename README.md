# Corylus Distraction-Free Wallpapers

Curated wallpaper and video collection used by [Corylus](https://github.com/LudoBermejoES/corylus) to offer background choices for its distraction-free writing mode.

## Origin

This repository is a fork of [mylinuxforwork/wallpaper](https://github.com/mylinuxforwork/wallpaper), the "ML4W Wallpaper Collection" — a personal wallpaper collection originally curated for tiling window managers. Corylus reuses that collection as a starting set of high-quality, distraction-free backgrounds, and adds/replaces images over time to fit its own use case.

## Why a separate repository

Corylus is a Tauri application; its main repository holds source code, not media. Bundling this collection there would bloat every clone and checkout with tens of megabytes of images that most contributors never need. Keeping it here instead lets Corylus:

- Reference this repo as a git submodule (`assets/distractionfree-wallpaper`) instead of committing binaries to the app repo's history.
- Download or update wallpapers independently of the app's release cycle.
- Diverge from upstream over time — adding, removing, or replacing images for distraction-free mode — without affecting the original collection.

## Updating from upstream

The original collection is tracked as the `upstream` remote:

```
git fetch upstream
git merge upstream/main
```

## License

See [LICENSE](LICENSE).
