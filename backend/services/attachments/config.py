"""Bounded defaults shared by API validation and isolated parsers."""

import os
import shutil
from pathlib import Path

MIB = 1024 * 1024
LIMITS = {
    "max_attachments": 9,
    "max_image_bytes": 10 * MIB,
    "max_document_bytes": 20 * MIB,
    "max_message_bytes": 50 * MIB,
    "max_user_bytes": 500 * MIB,
    "max_image_pixels": 40_000_000,
    "max_pages": 200,
}
# Images are normalized to at most 2048 px. Keep their context estimate internal;
# provider usage is authoritative and may differ from this planning allowance.
IMAGE_TOKEN_ESTIMATE = 20_000
EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
ZIP_MAX_BYTES = 200 * MIB
ZIP_MAX_ENTRIES = 10_000
MAX_TEXT_CHARS = 2_000_000
MAX_BLOCKS = 20_000
PARSER_TIMEOUT_SECONDS = 60
PARSER_MEMORY_BYTES = 768 * MIB
LEASE_SECONDS = 90
DRAFT_HOURS = 24
MAX_ATTEMPTS = 3


def storage_root() -> Path:
    from core.config import settings

    configured = os.environ.get("ATTACHMENT_STORAGE_DIR") or getattr(
        settings, "attachment_storage_dir", None
    )
    return (
        Path(configured or Path(__file__).resolve().parents[2] / "private_attachments")
        .expanduser()
        .resolve()
    )


def libreoffice_path() -> str | None:
    from core.config import settings

    configured = os.environ.get("ATTACHMENT_LIBREOFFICE_PATH") or getattr(
        settings, "attachment_libreoffice_path", None
    )
    if configured:
        return configured if Path(configured).is_file() else None
    mac_binary = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    return str(mac_binary) if mac_binary.is_file() else shutil.which("soffice")


def isolation_available() -> bool:
    import sys

    return bool(shutil.which("sandbox-exec") if sys.platform == "darwin" else shutil.which("bwrap"))
