"""
Download a small Vosk English model into the project 'models' folder.
Run once before first use:  python download_model.py
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from urllib.request import urlretrieve

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
MODEL_ZIP = "vosk-model-small-en-us-0.15.zip"
MODEL_DIR_NAME = "vosk-model-small-en-us-0.15"


def main() -> None:
    base = Path(__file__).resolve().parent
    models_dir = base / "models"
    models_dir.mkdir(exist_ok=True)
    zip_path = models_dir / MODEL_ZIP
    extract_to = models_dir / MODEL_DIR_NAME
    if (extract_to / "am").is_dir():
        print(f"Model already present at {extract_to}")
        return
    print(f"Downloading {MODEL_URL} ...")
    urlretrieve(MODEL_URL, zip_path)
    print("Extracting ...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(models_dir)
    zip_path.unlink()
    print(f"Done. Model is at {extract_to}")


if __name__ == "__main__":
    main()
