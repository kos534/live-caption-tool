"""User settings edited in the ⚙ Settings view: personal info, job info and the OpenAI API key.

Saved as settings.json next to the app. The API key is encrypted with Windows DPAPI, so the file
only decrypts for the same Windows user on the same machine; everything else is plain JSON.
"""

import base64
import ctypes
import html
import json
import logging
import re
import sys
import zipfile
from ctypes import wintypes
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

MAX_DOC_CHARS = 20000  # resume / job description text kept (and sent to the AI) at most


@dataclass
class UserSettings:
    # Personal info
    name: str = ""
    birthday: str = ""
    address: str = ""
    university: str = ""
    # Job
    resume_file: str = ""  # file name the resume text was loaded from (display only)
    resume_text: str = ""
    job_description: str = ""
    # Answer prompt: instructions for the AI ("" = the built-in default)
    answer_prompt: str = ""
    # Security (kept in memory in clear text, written to disk encrypted)
    openai_api_key: str = ""

    @classmethod
    def load(cls, path: Path) -> "UserSettings":
        settings = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return settings
        except (OSError, ValueError) as exc:
            log.warning("Couldn't read %s: %s", path, exc)
            return settings
        for f in fields(cls):
            value = data.get(f.name)
            if isinstance(value, str) and f.name != "openai_api_key":
                setattr(settings, f.name, value)
        if data.get("openai_api_key_dpapi"):
            try:
                settings.openai_api_key = _unprotect(base64.b64decode(data["openai_api_key_dpapi"])).decode("utf-8")
            except Exception as exc:  # copied from another user/machine, or corrupted
                log.warning("Couldn't decrypt the saved OpenAI API key: %s", exc)
        elif isinstance(data.get("openai_api_key"), str):
            settings.openai_api_key = data["openai_api_key"]  # saved where DPAPI wasn't available
        return settings

    def save(self, path: Path):
        data = asdict(self)
        key = data.pop("openai_api_key").strip()
        if key:
            try:
                data["openai_api_key_dpapi"] = base64.b64encode(_protect(key.encode("utf-8"))).decode("ascii")
            except Exception as exc:
                log.warning("DPAPI unavailable (%s); saving the API key unencrypted", exc)
                data["openai_api_key"] = key
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)  # never leave a half-written settings file behind


# ---- Windows DPAPI ---------------------------------------------------------------------------


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(func_name: str, data: bytes) -> bytes:
    if sys.platform != "win32":
        raise OSError("DPAPI is Windows-only")
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    func = getattr(ctypes.windll.crypt32, func_name)
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if not func(ctypes.byref(blob_in), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _protect(data: bytes) -> bytes:
    return _dpapi("CryptProtectData", data)


def _unprotect(data: bytes) -> bytes:
    return _dpapi("CryptUnprotectData", data)


# ---- resume upload ---------------------------------------------------------------------------

DOCUMENT_TYPES = [("Resume", "*.pdf *.docx *.txt *.md"), ("All files", "*.*")]


def read_document(path: Path) -> str:
    """Plain text of a .pdf, .docx or text file. Raises ValueError with a user-facing reason."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            text = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
        elif suffix == ".docx":
            text = _read_docx(path)
        elif suffix == ".doc":
            raise ValueError("Old .doc files aren't supported; save it as .docx or PDF")
        else:
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1252", errors="replace")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Couldn't read {path.name}: {exc}") from exc
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ValueError(f"No text found in {path.name} (a scanned PDF has no text layer)")
    return text[:MAX_DOC_CHARS]


def _read_docx(path: Path) -> str:
    """Paragraph text of a .docx, using only the standard library."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paragraphs = []
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        para = re.sub(r"<w:tab/>", "\t", para)
        para = re.sub(r"<w:br/>", "\n", para)
        parts = re.findall(r"<w:t(?: [^>]*)?>(.*?)</w:t>|(\t|\n)", para, flags=re.S)
        paragraphs.append("".join(t or ws for t, ws in parts))
    return html.unescape("\n".join(paragraphs))
