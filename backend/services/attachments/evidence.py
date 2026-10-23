"""Revalidate saved file sources against live ownership and immutable chunks."""

from models.attachment import Attachment, AttachmentChunk, MessageAttachment
from models import ChatMessage


def hydrate_message_sources(db, *, user_id: int, messages: list) -> dict[int, list[dict]]:
    """Two bounded bulk reads for any history page, never trust model locations.

    Unavailable/deleted sources preserve only display identity. Their saved
    excerpt is deliberately removed so deleting a document revokes readback.
    """
    from services.web_evidence import _sources

    output = {
        m.id: _sources((m.metadata_json or {}).get("web", {}).get("sources")) for m in messages
    }
    by_message = {m.id: m for m in messages if m.user_id == user_id}
    requested = {
        s["attachment_id"]
        for sources in output.values()
        for s in sources
        if s.get("kind") in {"document", "image"}
    }
    if not requested:
        return output
    records = (
        db.query(Attachment, MessageAttachment, ChatMessage)
        .join(MessageAttachment, MessageAttachment.attachment_id == Attachment.id)
        .join(ChatMessage, ChatMessage.id == MessageAttachment.user_message_id)
        .filter(
            Attachment.id.in_(requested),
            Attachment.user_id == user_id,
            Attachment.status == "ready",
            ChatMessage.user_id == user_id,
        )
        .all()
    )
    available = {a.id: (a, link, message) for a, link, message in records}
    chunk_ids = {
        s.get("chunk_id") for sources in output.values() for s in sources if s.get("chunk_id")
    }
    chunk_ids.update(
        c for sources in output.values() for s in sources for c in s.get("covered_chunk_ids", [])
    )
    chunks = (
        {
            (c.attachment_id, c.revision, c.chunk_id): c
            for c in db.query(AttachmentChunk)
            .filter(
                AttachmentChunk.attachment_id.in_(requested),
                AttachmentChunk.chunk_id.in_(chunk_ids),
            )
            .all()
        }
        if chunk_ids
        else {}
    )
    for message_id, sources in output.items():
        message = by_message.get(message_id)
        for index, source in enumerate(sources):
            if source.get("kind") not in {"document", "image"}:
                continue
            found = available.get(source["attachment_id"])
            valid = bool(message and found)
            if valid:
                attachment, link, origin = found
                valid = (
                    attachment.session_id == message.session_id
                    and attachment.topic_id == message.topic_id
                    and attachment.mode == message.mode
                    and origin.session_id == message.session_id
                    and link.revision == source["revision"] == attachment.revision
                )
                if source["kind"] == "document":
                    chunk = chunks.get((attachment.id, source["revision"], source["chunk_id"]))
                    valid = (
                        valid
                        and chunk is not None
                        and (chunk.locator or {}) == source.get("locator")
                    )
                    valid = valid and all(
                        (attachment.id, source["revision"], chunk_id) in chunks
                        for chunk_id in source.get("covered_chunk_ids", [])
                    )
                    if source.get("summary"):
                        covered = source.get("covered_chunk_ids", [])
                        valid = (
                            valid
                            and len(covered) == len(set(covered))
                            and source.get("coverage")
                            == [
                                chunks[(attachment.id, source["revision"], chunk_id)].locator
                                for chunk_id in covered
                                if (attachment.id, source["revision"], chunk_id) in chunks
                            ]
                        )
                    valid = valid and attachment.kind == "document"
                else:
                    valid = valid and attachment.kind == "image" and source.get("chunk_id") is None
            if not valid:
                sources[index] = {
                    key: value
                    for key, value in source.items()
                    if key not in {"coverage", "covered_chunk_ids"}
                }
                sources[index].update(deleted=True, excerpt="")
    return output
