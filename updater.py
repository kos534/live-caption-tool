"""Startup check for a newer version, published as a small JSON file on the Wonuva website.

version.json (see installer\\version.json):
    {"version": "2.1.0", "url": "https://wonuva.com/live-caption", "notes": "What's new, one line"}

Runs once in the background a few seconds after launch. Any failure (offline, bad JSON, site down)
is only logged: the check must never get in the way of captions.
"""

import json
import logging
import re
import threading
import urllib.request

log = logging.getLogger(__name__)


def parse_version(text: str) -> tuple:
    """'2.10.1' -> (2, 10, 1); anything after the numbers (e.g. '-beta') is ignored."""
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(p) for p in match.group(1).split(".")) if match else ()


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    width = max(len(a), len(b))
    return bool(a) and a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def check_for_update(url: str, current_version: str, timeout: float = 8.0):
    """{'version', 'url', 'notes'} if `url` announces a newer version than current_version, else None."""
    request = urllib.request.Request(url, headers={"User-Agent": f"WonuvaLiveCaption/{current_version}"})
    with urllib.request.urlopen(request, timeout=timeout) as r:
        info = json.loads(r.read(65536).decode("utf-8-sig"))
    version = str(info.get("version", ""))
    download = str(info.get("url", ""))
    if not (is_newer(version, current_version) and download.startswith("https://")):
        return None
    return {"version": version, "url": download, "notes": str(info.get("notes", ""))[:200]}


def check_in_background(url: str, current_version: str, on_update):
    """Run check_for_update on a thread; on_update(info) is called from that thread if newer."""

    def run():
        try:
            info = check_for_update(url, current_version)
        except Exception as exc:
            log.info("Update check skipped: %s", exc)
            return
        if info:
            log.info("Update available: %s", info["version"])
            on_update(info)
        else:
            log.info("Up to date (v%s)", current_version)

    if url:
        threading.Thread(target=run, name="update-check", daemon=True).start()
