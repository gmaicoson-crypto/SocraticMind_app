from pathlib import Path

from fastapi import HTTPException, UploadFile
from core.config import settings

UPLOAD_DIR = (
    Path(settings.avatar_storage_dir).expanduser().resolve()
    if settings.avatar_storage_dir
    else Path(__file__).resolve().parents[1] / "uploads" / "avatars"
)
ALLOWED_AVATAR_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024


async def read_avatar_upload(file: UploadFile) -> tuple[str, bytes]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_AVATAR_EXT:
        raise HTTPException(status_code=400, detail="不支持的图片格式")

    data = await file.read(MAX_AVATAR_SIZE + 1)
    if len(data) > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail="图片大小不能超过 5MB")
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    return suffix, data
