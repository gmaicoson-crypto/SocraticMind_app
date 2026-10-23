"""Local private storage. Keys never contain filenames supplied by users."""

import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from typing import BinaryIO

from core.errors import ApiError
from .config import storage_root


class AttachmentStorage:
    def __init__(self, root: Path | None = None):
        self.root = (root or storage_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, key: str) -> Path:
        result = (self.root / key).resolve()
        if not result.is_relative_to(self.root) or result == self.root:
            raise ValueError("Invalid private storage key")
        return result

    def stage(self, source: BinaryIO, limit: int) -> tuple[Path, int, str]:
        temporary = self.root / ".incoming"
        temporary.mkdir(exist_ok=True, mode=0o700)
        fd, filename = tempfile.mkstemp(dir=temporary)
        target = Path(filename)
        size = 0
        digest = hashlib.sha256()
        try:
            with os.fdopen(fd, "wb") as output:
                while block := source.read(1024 * 1024):
                    size += len(block)
                    if size > limit:
                        raise ApiError(
                            status_code=413,
                            code="ATTACHMENT_TOO_LARGE",
                            message="文件超过大小限制",
                            retryable=False,
                        )
                    digest.update(block)
                    output.write(block)
            if not size:
                raise ApiError(
                    status_code=422,
                    code="ATTACHMENT_PARSE_FAILED",
                    message="不能上传空文件",
                    retryable=False,
                )
            return target, size, digest.hexdigest()
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def publish(self, temporary: Path, key: str) -> None:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(temporary, target)

    def read(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def delete(self, prefix: str) -> None:
        target = self.path(prefix)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
