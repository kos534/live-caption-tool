"""Pre-download the faster-whisper models for the given presets into config.MODELS_DIR.

Usage: python download_models.py [preset ...]   (default: config.DEFAULT_MODEL)

build_exe.bat runs this and copies models/ next to the exe, so the built app works offline
without downloading anything on first launch.
"""

import sys

from faster_whisper.utils import download_model

import config


def main():
    presets = sys.argv[1:] or [config.DEFAULT_MODEL]
    sizes = []
    for preset in presets:
        if preset not in config.MODEL_PRESETS:
            sys.exit(f"Unknown preset {preset!r}; choose from {list(config.MODEL_PRESETS)}")
        sizes.extend(s for s in config.MODEL_PRESETS[preset] if s not in sizes)
    for size in sizes:
        print(f"Fetching {size} ...", flush=True)
        path = download_model(size, cache_dir=str(config.MODELS_DIR))
        print(f"  -> {path}", flush=True)


if __name__ == "__main__":
    main()
