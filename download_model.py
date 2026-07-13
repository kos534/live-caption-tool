"""
Pre-download a faster-whisper model into the project 'models' folder so the
app can run fully offline after this one-time step (and so an exe build can
optionally bundle a model).

Usage:
    python download_model.py --model-size small.en
"""
from __future__ import annotations

import argparse

from config import DEFAULTS, MODEL_SIZES
from whisper_engine import models_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-size",
        choices=MODEL_SIZES,
        default=DEFAULTS["model_size"],
        help=f"Model size to download (default: {DEFAULTS['model_size']})",
    )
    args = parser.parse_args()

    from faster_whisper.utils import download_model

    out_dir = models_dir() / f"faster-whisper-{args.model_size}"
    if out_dir.is_dir() and any(out_dir.iterdir()):
        print(f"Model already present at {out_dir}")
        return
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading '{args.model_size}' ...")
    download_model(args.model_size, output_dir=str(out_dir))
    print(f"Done. Model is at {out_dir}")


if __name__ == "__main__":
    main()
