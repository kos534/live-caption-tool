"""Download the speech models from the command line (the app also does this on first run).

Usage: python download_models.py [--to DIR] [preset ...]   (default preset: config.DEFAULT_MODEL)

Models go to config.MODELS_DIR (%LOCALAPPDATA%\\Wonuva Live Caption\\models) unless --to is given.
For an offline build that ships the models, download into the build: --to dist\\WonuvaLiveCaption\\models
"""

import sys
import time
from pathlib import Path

import config
from model_download import ModelDownloader, find_model, format_size


def main():
    args = sys.argv[1:]
    target = config.MODELS_DIR
    if args[:1] == ["--to"] and len(args) >= 2:
        target, args = Path(args[1]), args[2:]
    presets = args or [config.DEFAULT_MODEL]
    sizes = []
    for preset in presets:
        if preset not in config.MODEL_PRESETS:
            sys.exit(f"Unknown preset {preset!r}; choose from {list(config.MODEL_PRESETS)}")
        sizes.extend(s for s in config.MODEL_PRESETS[preset] if s not in sizes)

    # Without --to, a model the app can already find anywhere (e.g. models\ in a source checkout)
    # counts as installed.
    search = [target] if target != config.MODELS_DIR else config.MODEL_SEARCH_DIRS
    missing = [s for s in sizes if not find_model(s, search)]
    if not missing:
        print("All models already installed:")
        for s in sizes:
            print(f"  {s} -> {find_model(s, search)}")
        return
    print(f"Downloading {', '.join(missing)} to {target}", flush=True)
    d = ModelDownloader(missing, target, user_agent=f"WonuvaLiveCaption/{config.APP_VERSION}")
    d.start()
    while d.running:
        time.sleep(1)
        done, total, speed = d.progress()
        if total:
            print(f"\r  {format_size(done)} of {format_size(total)}  {format_size(speed)}/s   ", end="", flush=True)
    print()
    if not d.finished:
        sys.exit(f"Download failed: {d.error}")
    for s in missing:
        print(f"  {s} -> {find_model(s, [target])}")


if __name__ == "__main__":
    main()
