"""Pure reply metadata projection; lifecycle retains transaction, version and token ownership."""

from copy import deepcopy

from models import ChatMessage
from services.chat_feedback import normalized_usage
from services.web_evidence import cited_source_ids


TERMINAL_STATUSES = {"complete", "failed", "interrupted"}


def web_metadata(
    message: ChatMessage,
    content: str,
    *,
    web: dict | None = None,
    status: str = "generating",
    error_code: str | None = None,
) -> dict:
    snapshot = deepcopy(web if web is not None else (message.metadata_json or {}).get("web"))
    if snapshot is None:
        return {}
    snapshot["cited_source_ids"] = cited_source_ids(content, snapshot.get("sources", []))
    if status in TERMINAL_STATUSES and snapshot.get("status") in {"deciding", "searching"}:
        snapshot["status"] = "failed"
        snapshot["error_code"] = error_code or "WEB_PREPARATION_INTERRUPTED"
    return {"web": snapshot}


def usage_metadata(usage: object) -> dict:
    value = normalized_usage(usage)
    return {"usage": value} if value is not None else {}
