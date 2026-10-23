"""Database leased jobs; each parser runs in a killable filesystem/network sandbox."""

from datetime import timedelta
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from sqlalchemy import or_

from core.database import SessionLocal
from models.attachment import Attachment, AttachmentChunk, AttachmentCleanup, AttachmentWorkerSlot
from .config import (
    LEASE_SECONDS,
    MAX_ATTEMPTS,
    PARSER_MEMORY_BYTES,
    PARSER_TIMEOUT_SECONDS,
    libreoffice_path,
)
from .service import mark_deleted, utcnow
from .storage import AttachmentStorage

log = logging.getLogger(__name__)


def _sandbox_command(source: Path, output: Path, executable: str | None) -> list[str]:
    parser = Path(__file__).with_name("parsers.py").resolve()
    command = [
        sys.executable,
        "-I",
        str(parser),
        str(source),
        source.suffix.lower(),
        str(output),
        executable or "",
    ]
    trusted = {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), parser.parent}
    if executable:
        binary = Path(executable).resolve()
        # The distribution includes helper binaries, resources and fonts.
        installation = next((parent for parent in binary.parents if parent.suffix == ".app"), None)
        if installation is None:
            # Bundled runtimes place a wrapper at dependencies/bin/override/soffice.
            installation = (
                binary.parent.parent.parent
                if binary.parent.name == "override" and binary.parent.parent.name == "bin"
                else binary.parent
            )
        if installation == Path("/"):
            raise RuntimeError("LibreOffice must be installed in a dedicated directory")
        trusted.add(installation)
    if sys.platform == "darwin":
        sandbox = shutil.which("sandbox-exec")
        if not sandbox:
            raise RuntimeError("Parser sandbox unavailable")
        readable = [
            "/System",
            "/usr",
            "/bin",
            "/sbin",
            "/Library",
            "/private/var/db",
            "/dev",
            "/opt/homebrew",
            "/usr/local",
        ]
        readable.extend(str(path) for path in trusted)
        rules = [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow file-read-metadata)",
            '(allow file-read* (literal "/"))',
        ]
        rules.extend(f"(allow file-read* (subpath {json.dumps(path)}))" for path in readable)
        rules.append(f"(allow file-read* (literal {json.dumps(str(source))}))")
        rules.append(f"(allow file-read* file-write* (subpath {json.dumps(str(output))}))")
        rules.append('(allow file-write* (literal "/dev/null"))')
        return [sandbox, "-p", "\n".join(rules), *command]
    sandbox = shutil.which("bwrap")
    if not sandbox:
        raise RuntimeError("Parser sandbox unavailable")
    result = [
        sandbox,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]
    for path in {Path("/usr"), Path("/lib"), Path("/lib64"), Path("/bin"), *trusted}:
        if path.exists():
            result.extend(["--ro-bind", str(path), str(path)])
    for path in (Path("/etc/fonts"), Path("/var/cache/fontconfig")):
        if path.exists():
            result.extend(["--ro-bind", str(path), str(path)])
    result.extend(
        [
            "--ro-bind",
            str(source),
            str(source),
            "--bind",
            str(output),
            str(output),
            "--chdir",
            str(output),
            *command,
        ]
    )
    return result


def execute_parser(source: Path, output: Path, stop_event=None) -> dict:
    import psutil

    command = _sandbox_command(source, output, libreoffice_path())
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(output),
        "TMPDIR": str(output),
        "LANG": "en_US.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=output,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    peak = 0
    failure = None
    try:
        while process.poll() is None:
            if (
                stop_event and stop_event.is_set()
            ) or time.monotonic() - started > PARSER_TIMEOUT_SECONDS:
                failure = "解析已中断或超时，请重试或拆分文件"
                break
            try:
                tree = [psutil.Process(process.pid)]
                tree.extend(tree[0].children(recursive=True))
                used = sum(child.memory_info().rss for child in tree if child.is_running())
                peak = max(peak, used)
                if used > PARSER_MEMORY_BYTES:
                    failure = "解析所需内存超过限制，请拆分文件"
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            if stop_event:
                stop_event.wait(0.05)
            else:
                time.sleep(0.05)
    finally:
        # Kill the process group too: LibreOffice may outlive a failed Python parser.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
    log.info(
        "attachment_parse elapsed_ms=%d peak_rss_bytes=%d",
        int((time.monotonic() - started) * 1000),
        peak,
    )
    result_path = output / "result.json"
    if failure or not result_path.is_file() or result_path.stat().st_size > 16 * 1024 * 1024:
        return {
            "error_code": "ATTACHMENT_PARSE_FAILED",
            "error_message": failure or "解析进程异常退出，请重试或检查服务配置",
        }
    return json.loads(result_path.read_text(encoding="utf-8"))


def _claim(session_factory):
    now = utcnow()
    with session_factory() as db:
        # Migrations create exactly two global slots. Tests using metadata need them too.
        if db.query(AttachmentWorkerSlot.id).count() == 0:
            db.add_all([AttachmentWorkerSlot(id=1), AttachmentWorkerSlot(id=2)])
            try:
                db.commit()
            except Exception:
                db.rollback()
        slot = (
            db.query(AttachmentWorkerSlot)
            .filter(
                or_(
                    AttachmentWorkerSlot.lease_until.is_(None),
                    AttachmentWorkerSlot.lease_until < now,
                )
            )
            .order_by(AttachmentWorkerSlot.id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if slot is None:
            return None
        row = (
            db.query(Attachment)
            .filter(
                or_(
                    Attachment.status == "pending",
                    (Attachment.status == "processing") & (Attachment.lease_until < now),
                ),
                or_(Attachment.next_retry_at.is_(None), Attachment.next_retry_at <= now),
                or_(Attachment.expires_at.is_(None), Attachment.expires_at > now),
            )
            .order_by(Attachment.created_at, Attachment.id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None:
            return None
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
            row.error_code = "ATTACHMENT_PARSE_FAILED"
            row.error_message = "解析多次中断，请移除后重新上传"
            row.lease_token = row.lease_until = None
            db.commit()
            return None
        token = str(uuid.uuid4())
        row.status = "processing"
        row.attempts += 1
        row.lease_token = slot.lease_token = token
        row.lease_until = slot.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        claim = {
            "id": row.id,
            "revision": row.revision,
            "token": token,
            "storage_key": row.storage_key,
            "slot": slot.id,
        }
        queued_ms = (
            max(0, int((now - row.created_at.replace(tzinfo=now.tzinfo)).total_seconds() * 1000))
            if row.created_at
            else 0
        )
        attempts = row.attempts
        db.commit()
        log.info("attachment_job_claimed queue_ms=%d attempt=%d", queued_ms, attempts)
        return claim


def _publish_result(session_factory, claim, result, output):
    # Include escaped JSON metadata in the bound, reserving room for DB row/index
    # overhead and the separately bounded 512 KiB summary cache within quota.
    if len(json.dumps(result, ensure_ascii=True).encode("utf-8")) > 16 * 1024 * 1024:
        result = {
            "error_code": "ATTACHMENT_TOO_LARGE",
            "error_message": "解析结果超过存储限制，请拆分文件",
        }
    derived_size = sum(
        (output / name).stat().st_size
        for name in ("image.jpg", "preview.jpg")
        if (output / name).is_file()
    )
    if derived_size > 12 * 1024 * 1024:
        result = {"error_code": "ATTACHMENT_TOO_LARGE", "error_message": "图片处理结果超过存储限制"}
    storage = AttachmentStorage()
    with session_factory() as db:
        row = (
            db.query(Attachment)
            .filter(
                Attachment.id == claim["id"],
                Attachment.status == "processing",
                Attachment.lease_token == claim["token"],
                Attachment.revision == claim["revision"],
                Attachment.lease_until > utcnow(),
            )
            .with_for_update()
            .first()
        )
        if row is not None:
            if result.get("error_code"):
                row.status = "failed"
                row.error_code = result["error_code"]
                row.error_message = result["error_message"]
            else:
                # Only fixed generated filenames may be published from the sandbox.
                prefix = f"{row.id}/revision-{row.revision}"
                for key, filename in (("image_key", "image.jpg"), ("preview_key", "preview.jpg")):
                    if (output / filename).is_file():
                        storage.publish(output / filename, f"{prefix}/{filename}")
                        setattr(row, key, f"{prefix}/{filename}")
                for name in ("pages", "width", "height", "coverage"):
                    setattr(row, name, result.get(name))
                row.status = result["status"]
                row.warnings = result.get("warnings", [])
                row.error_code = row.error_message = None
                db.query(AttachmentChunk).filter(
                    AttachmentChunk.attachment_id == row.id,
                    AttachmentChunk.revision == row.revision,
                ).delete(synchronize_session=False)
                db.add_all(
                    [
                        AttachmentChunk(attachment_id=row.id, revision=row.revision, **block)
                        for block in result.get("chunks", [])
                    ]
                )
            row.lease_token = row.lease_until = None
        db.query(AttachmentWorkerSlot).filter(
            AttachmentWorkerSlot.id == claim["slot"],
            AttachmentWorkerSlot.lease_token == claim["token"],
        ).update({"lease_token": None, "lease_until": None}, synchronize_session=False)
        db.commit()


def run_one_attachment_job(
    session_factory=SessionLocal, stop_event=None, parser=execute_parser
) -> bool:
    claim = _claim(session_factory)
    if claim is None:
        return False
    storage = AttachmentStorage()
    with tempfile.TemporaryDirectory(prefix="attachment-parse-") as directory:
        output = Path(directory).resolve()
        try:
            result = parser(storage.path(claim["storage_key"]), output, stop_event)
        except Exception as exc:
            log.warning("attachment_parse_failed error_type=%s", type(exc).__name__)
            result = {
                "error_code": "ATTACHMENT_PARSE_FAILED",
                "error_message": "解析服务暂时不可用，请稍后重试",
            }
        _publish_result(session_factory, claim, result, output)
    return True


def run_cleanup(session_factory=SessionLocal) -> bool:
    storage = AttachmentStorage()
    with session_factory() as db:
        expired = (
            db.query(Attachment)
            .filter(
                Attachment.session_id.is_(None),
                Attachment.status != "deleted",
                Attachment.expires_at < utcnow(),
            )
            .with_for_update(skip_locked=True)
            .limit(50)
            .all()
        )
        mark_deleted(db, expired)
        db.commit()  # Revoke access before deleting physical data.
        jobs = db.query(AttachmentCleanup).order_by(AttachmentCleanup.created_at).limit(50).all()
        for job in jobs:
            storage.delete(job.storage_prefix)
            db.delete(job)
        db.commit()
        # Reconcile interrupted writes after a grace period; in-flight uploads are newer.
        cutoff = time.time() - 24 * 3600
        known = {
            item[0] for item in db.query(Attachment.id).filter(Attachment.status != "deleted").all()
        }
        for path in storage.root.iterdir():
            if path.name == ".incoming":
                for temporary in path.iterdir():
                    if temporary.is_file() and temporary.stat().st_mtime < cutoff:
                        temporary.unlink(missing_ok=True)
            elif path.is_dir() and path.name not in known and path.stat().st_mtime < cutoff:
                storage.delete(path.name)
        return bool(expired or jobs)


class AttachmentWorker:
    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._run, name=f"attachment-worker-{index}", daemon=True)
            for index in range(2)
        ]

    def start(self):
        for thread in self._threads:
            thread.start()

    def stop(self):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=6)

    def _run(self):
        cleanup_at = 0
        while not self._stop.is_set():
            try:
                if time.monotonic() >= cleanup_at:
                    run_cleanup(self.session_factory)
                    cleanup_at = time.monotonic() + 60
                did_work = run_one_attachment_job(self.session_factory, self._stop)
            except Exception as exc:
                log.warning("attachment_worker_failed error_type=%s", type(exc).__name__)
                did_work = False
            self._stop.wait(0.1 if did_work else 2)
