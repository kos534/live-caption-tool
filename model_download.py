"""Finding and downloading the speech models.

Installed copies of the app don't ship the models (~4.4 GB for large-v3); they're downloaded on
first run into config.MODELS_DIR, one plain folder per model (faster-whisper-<size>\\). The files come
straight from the model's Hugging Face repo over HTTPS, which gives exact progress, resumes an
interrupted download (.part files + HTTP Range) and checks each file's SHA-256 against the repo.

Models in Hugging Face's cache layout (models--Systran--...) are found too, so a source checkout
whose models\\ folder was filled by older versions of download_models.py keeps working.
"""

import hashlib
import json
import logging
import threading
import time
import urllib.request
from fnmatch import fnmatch
from pathlib import Path

log = logging.getLogger(__name__)

HF_URL = "https://huggingface.co"
# faster-whisper model sizes -> their Hugging Face repos (same as faster_whisper.utils._MODELS).
REPOS = {
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "base.en": "Systran/faster-whisper-base.en",
    "small.en": "Systran/faster-whisper-small.en",
    "medium.en": "Systran/faster-whisper-medium.en",
    "large-v3": "Systran/faster-whisper-large-v3",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
}
# The files faster-whisper needs (same patterns faster_whisper.utils.download_model uses).
FILE_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
COMPLETE_MARKER = ".complete"  # written once every file of a model is in place and verified
CHUNK = 1 << 20


def model_folder(models_dir, size: str) -> Path:
    return Path(models_dir) / f"faster-whisper-{size}"


def find_model(size: str, search_dirs) -> str:
    """Path of an installed model (for WhisperModel), or "" if it isn't installed anywhere."""
    for d in search_dirs:
        folder = model_folder(d, size)
        if (folder / COMPLETE_MARKER).exists():
            return str(folder)
        hf_cache = Path(d) / ("models--" + REPOS.get(size, "").replace("/", "--")) / "snapshots"
        if hf_cache.is_dir():
            for snapshot in sorted(hf_cache.iterdir(), reverse=True):
                if (snapshot / "model.bin").exists() and (snapshot / "config.json").exists():
                    return str(snapshot)
    return ""


def missing_models(sizes, search_dirs) -> list:
    return [s for s in sizes if not find_model(s, search_dirs)]


def format_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit in ("GB", "MB") else f"{n:.0f} {unit}"
        n /= 1024


class DownloadCancelled(Exception):
    pass


class ModelDownloader:
    """Downloads models in a background thread; poll progress() from the UI."""

    def __init__(self, sizes, target_dir, user_agent: str = "WonuvaLiveCaption"):
        self.sizes = list(sizes)
        self.target_dir = Path(target_dir)
        self.user_agent = user_agent
        self.total = 0  # bytes, known once the file list is fetched
        self.done = 0
        self.error = ""
        self.finished = False
        self._cancel = threading.Event()
        self._samples = []  # (time, done) for the speed estimate
        self._thread = None

    def start(self):
        self._cancel.clear()
        self.error = ""
        self.finished = False
        self._thread = threading.Thread(target=self._run, name="model-download", daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancel.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def progress(self):
        """(done_bytes, total_bytes, bytes_per_second)."""
        now = time.monotonic()
        self._samples.append((now, self.done))
        self._samples = [s for s in self._samples if now - s[0] <= 5.0]
        t0, d0 = self._samples[0]
        speed = (self.done - d0) / (now - t0) if now - t0 >= 0.5 else 0.0
        return self.done, self.total, speed

    # ---- worker ---------------------------------------------------------------------------

    def _request(self, url: str, start: int = 0):
        headers = {"User-Agent": self.user_agent}
        if start:
            headers["Range"] = f"bytes={start}-"
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30)

    def _file_list(self, size: str) -> list:
        """[(name, bytes, sha256 or None)] of the files this model needs."""
        repo = REPOS[size]
        with self._request(f"{HF_URL}/api/models/{repo}?blobs=true") as r:
            info = json.load(r)
        files = []
        for sib in info.get("siblings", []):
            name = sib.get("rfilename", "")
            if any(fnmatch(name, p) for p in FILE_PATTERNS):
                lfs = sib.get("lfs") or {}
                files.append((name, int(sib.get("size") or lfs.get("size") or 0), lfs.get("sha256")))
        if not any(name == "model.bin" for name, _, _ in files):
            raise RuntimeError(f"{repo} has no model.bin")
        return files

    def _run(self):
        try:
            plan = [(size, self._file_list(size)) for size in self.sizes]
            self.total = sum(n for _, files in plan for _, n, _ in files)
            # Count what's already on disk (finished files and partial downloads) as done.
            self.done = 0
            for size, files in plan:
                folder = model_folder(self.target_dir, size)
                for name, n, _ in files:
                    dest, part = folder / name, folder / (name + ".part")
                    if dest.exists() and dest.stat().st_size == n:
                        self.done += n
                    elif part.exists():
                        self.done += min(part.stat().st_size, n)
            for size, files in plan:
                folder = model_folder(self.target_dir, size)
                folder.mkdir(parents=True, exist_ok=True)
                for name, n, sha in files:
                    self._download_file(REPOS[size], name, n, sha, folder)
                (folder / COMPLETE_MARKER).write_text("ok", encoding="ascii")
                log.info("Model %s downloaded to %s", size, folder)
            self.finished = True
        except DownloadCancelled:
            log.info("Model download paused")
        except Exception as exc:
            log.exception("Model download failed")
            self.error = str(exc) or exc.__class__.__name__

    def _download_file(self, repo: str, name: str, size: int, sha256, folder: Path):
        dest, part = folder / name, folder / (name + ".part")
        if dest.exists() and dest.stat().st_size == size:
            return
        start = part.stat().st_size if part.exists() else 0
        if start > size:
            part.unlink()
            self.done -= start
            start = 0
        digest = hashlib.sha256() if sha256 else None
        if digest and start:  # resuming: hash what's already there first
            with open(part, "rb") as f:
                for block in iter(lambda: f.read(CHUNK), b""):
                    digest.update(block)
        with self._request(f"{HF_URL}/{repo}/resolve/main/{name}", start) as r:
            if start and r.status != 206:  # server ignored the Range header: start over
                self.done -= start
                start = 0
                digest = hashlib.sha256() if sha256 else None
            with open(part, "ab" if start else "wb") as f:
                while True:
                    if self._cancel.is_set():
                        raise DownloadCancelled()
                    block = r.read(CHUNK)
                    if not block:
                        break
                    f.write(block)
                    if digest:
                        digest.update(block)
                    self.done += len(block)
        got = part.stat().st_size
        if got != size:
            raise RuntimeError(f"{name}: got {format_size(got)} of {format_size(size)}; try again")
        if digest and digest.hexdigest() != sha256:
            part.unlink()
            self.done -= size
            raise RuntimeError(f"{name} was corrupted in transit; try again")
        part.replace(dest)


# Rough download sizes, shown before the exact file list has been fetched.
APPROX_BYTES = {
    "tiny.en": 75_000_000,
    "base.en": 145_000_000,
    "small.en": 485_000_000,
    "medium.en": 1_530_000_000,
    "large-v3": 3_090_000_000,
    "distil-large-v3": 1_510_000_000,
}
