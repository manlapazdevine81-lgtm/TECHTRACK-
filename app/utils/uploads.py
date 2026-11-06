"""Safe file attachment handling for Organizational Records (T14, approved).

Threat model this module addresses:
  * **Path traversal** — the client-supplied name is NEVER used as a path. The
    stored name is a fresh UUID4 plus a validated extension, and every read/write
    is resolved and checked to stay inside the upload root.
  * **Overwrite of unrelated files** — UUID names make collisions practically
    impossible, and the writer refuses to reuse an existing name regardless.
  * **Executables / arbitrary types** — a strict extension allowlist, applied to
    the *sanitised* filename, plus an extension re-check on download.
  * **Oversized uploads** — capped at 10 MB at both the Flask request level
    (`MAX_CONTENT_LENGTH`) and here (`MAX_ATTACHMENT_BYTES`).
  * **Public exposure** — the upload root lives under `instance/`, which is
    outside `static/`, so no file is served by Flask's static handler. Downloads
    go only through the authorized route in `app/routes/records.py`.

Nothing here decides WHO may upload or download; that stays in the routes.
"""
from __future__ import annotations

import pathlib
import uuid

from werkzeug.utils import secure_filename

# The only approved attachment types (T14).
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({"doc", "docx", "csv", "pdf"})

# 10 MB — documented in docs/REQUIREMENTS.md alongside T14.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class UploadError(ValueError):
    """A rejected upload. The message is safe to show to the user."""


def upload_root(app) -> pathlib.Path:
    """The directory attachments are stored in; created on first use.

    `instance/uploads/records/` — `instance/` is outside `static/`, so nothing
    here is reachable over HTTP except through the download route.
    """
    root = pathlib.Path(app.instance_path) / "uploads" / "records"
    root.mkdir(parents=True, exist_ok=True)
    return root


def extension_of(filename: str) -> str:
    """Lower-case extension without the dot ('' when there is none)."""
    name = secure_filename(filename or "")
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[1].lower()


def is_allowed(filename: str) -> bool:
    return extension_of(filename) in ALLOWED_EXTENSIONS


def _clean_display_name(filename: str) -> str:
    """A safe, human-readable original name, preserving the extension.

    `secure_filename` strips directory components and unsafe characters, which is
    exactly what we want to record and show. It is display-only — never a path.
    """
    cleaned = secure_filename(filename or "")
    if not cleaned:
        raise UploadError("The file name is not valid.")
    return cleaned[:255]


def _validate_size(size: int) -> None:
    if size <= 0:
        raise UploadError("The selected file is empty.")
    if size > MAX_ATTACHMENT_BYTES:
        raise UploadError(
            f"Attachments must be 10 MB or smaller (this file is "
            f"{size / (1024 * 1024):.1f} MB)."
        )


def save_attachment(app, file_storage) -> dict:
    """Validate and store one uploaded file.

    Returns ``{"key", "name", "size"}`` where:
      * ``key``  — the opaque UUID filename to store in `file_url`;
      * ``name`` — the sanitised ORIGINAL filename to store in `attachment_name`;
      * ``size`` — byte count for `attachment_size`.

    Raises `UploadError` (never a bare exception) on any rejection. On failure
    nothing is written to disk.
    """
    if file_storage is None or not getattr(file_storage, "filename", ""):
        raise UploadError("Choose a file to attach.")

    original = file_storage.filename
    ext = extension_of(original)
    if not ext:
        raise UploadError("The file has no extension. Allowed types: .doc, .docx, .csv, .pdf.")
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(f".{e}" for e in sorted(ALLOWED_EXTENSIONS))
        raise UploadError(f"Unsupported file type (.{ext}). Allowed types: {allowed}.")

    display_name = _clean_display_name(original)

    # Measure the size without trusting Content-Length.
    stream = file_storage.stream
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    _validate_size(size)

    root = upload_root(app)
    key = f"{uuid.uuid4().hex}.{ext}"
    target = safe_path(root, key)
    if target.exists():  # astronomically unlikely; never overwrite regardless
        raise UploadError("Could not store the file. Please try again.")

    try:
        file_storage.save(target)
    except OSError:
        # Clean up a partial write so a failed save leaves nothing behind.
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise UploadError("The file could not be saved. Please try again.") from None

    return {"key": key, "name": display_name, "size": size}


def safe_path(root: pathlib.Path, key: str) -> pathlib.Path:
    """Resolve `key` under `root`, refusing anything that escapes it.

    This is the defence that makes traversal impossible even if a stored key were
    ever tampered with in the database.
    """
    if not key or "/" in key or "\\" in key or key in (".", ".."):
        raise UploadError("That attachment cannot be found.")
    candidate = (root / key).resolve()
    root_resolved = root.resolve()
    if root_resolved not in candidate.parents:
        raise UploadError("That attachment cannot be found.")
    return candidate


def attachment_path(app, key: str) -> pathlib.Path:
    """Absolute path of a stored attachment, or `UploadError` if unavailable."""
    if not key:
        raise UploadError("That attachment cannot be found.")
    if extension_of(key) not in ALLOWED_EXTENSIONS:
        raise UploadError("That attachment cannot be found.")
    path = safe_path(upload_root(app), key)
    if not path.is_file():
        raise UploadError("That attachment is no longer available.")
    return path


def delete_attachment(app, key: str | None) -> None:
    """Best-effort removal of a stored file. Never raises.

    Called ONLY after the database transaction that replaced the attachment has
    committed, so a failed upload/database update can never destroy the old file.
    """
    if not key:
        return
    try:
        safe_path(upload_root(app), key).unlink(missing_ok=True)
    except (UploadError, OSError):
        # A leftover file is harmless; failing the user's request is not.
        pass
