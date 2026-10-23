"""Bounded structural and Chinese-aware retrieval over already parsed chunks."""

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from core.context_budget import count_text
from core.errors import ApiError

MAX_DOCUMENTS = 20
MAX_CHUNKS = 5000
MAX_SELECTED_CHUNKS = 48


@dataclass(frozen=True)
class Chunk:
    attachment_id: str
    revision: int
    chunk_id: str
    position: int
    text: str
    locator: dict
    title_path: object = None
    block_type: str = "paragraph"


@lru_cache(maxsize=512)
def terms(text: str) -> Counter:
    # Chinese word boundaries are not whitespace boundaries. Character bigrams
    # keep terms like 梯度下降 discoverable without an English-only tokenizer.
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
        if len(run) == 1:
            tokens.append(run)
    return Counter(tokens)


def requested_location(question: str) -> tuple[str, int, int] | None:
    match = re.search(r"第?\s*(\d+)\s*(?:[-—~至到]\s*(\d+)\s*)?(页|张|段)", question)
    if not match:
        match = re.search(r"\b(page|slide|paragraph)s?\s+(\d+)(?:\s*[-–]\s*(\d+))?", question, re.I)
        if not match:
            return None
        kind, start, end = (
            match.group(1).lower(),
            int(match.group(2)),
            int(match.group(3) or match.group(2)),
        )
    else:
        kind, start, end = (
            {"页": "page", "张": "slide", "段": "paragraph"}[match.group(3)],
            int(match.group(1)),
            int(match.group(2) or match.group(1)),
        )
    return kind, min(start, end), max(start, end)


def is_full_summary(question: str) -> bool:
    return (
        bool(re.search(r"总结|概括|概述|总结全文|summari[sz]e|summary|overview", question, re.I))
        and requested_location(question) is None
    )


class AttachmentRetriever:
    def select(
        self, chunks: list[Chunk], question: str, *, model_id: str, token_budget: int
    ) -> list[Chunk]:
        if len(chunks) > MAX_CHUNKS:
            raise ApiError(
                status_code=422,
                code="ATTACHMENT_CONTEXT_LIMIT",
                message="会话资料过多，请指定文件或缩小范围。",
                retryable=False,
            )
        location = requested_location(question)
        if location:
            kind, start, end = location
            keys = [kind, "slide"] if kind == "page" else [kind]
            exact = [
                c
                for c in chunks
                if any(
                    type(c.locator.get(key)) is int and start <= c.locator[key] <= end
                    for key in keys
                )
            ]
            if exact:
                chunks = exact
        all_cost = sum(count_text(c.text, model_id) + 180 for c in chunks)
        if all_cost <= token_budget and len(chunks) <= MAX_SELECTED_CHUNKS:
            return chunks
        query = terms(question)
        document_frequency = Counter(term for c in chunks for term in terms(c.text))
        ranked = []
        for c in chunks:
            counts = terms(c.text)
            score = sum(
                (1 + math.log(counts[t])) * math.log(1 + len(chunks) / (1 + document_frequency[t]))
                for t in query
                if counts[t]
            )
            heading = str(c.title_path or "")
            score += sum(3 for t in query if t in heading)
            ranked.append((score, c))
        ranked.sort(key=lambda item: (-item[0], item[1].position))
        selected, used = [], 0
        ordered = {(c.attachment_id, c.position): c for c in chunks}
        for _, match in ranked:
            for c in (
                match,
                ordered.get((match.attachment_id, match.position - 1)),
                ordered.get((match.attachment_id, match.position + 1)),
            ):
                if c is None or c in selected:
                    continue
                cost = count_text(c.text, model_id) + 180
                if used + cost <= token_budget:
                    selected.append(c)
                    used += cost
                if len(selected) >= MAX_SELECTED_CHUNKS:
                    break
            if len(selected) >= MAX_SELECTED_CHUNKS:
                break
        if not selected and chunks:
            raise ApiError(
                status_code=422,
                code="ATTACHMENT_CONTEXT_LIMIT",
                message="资料片段超过当前模型容量，请缩小范围或选择更大上下文的模型。",
                retryable=False,
            )
        return sorted(selected, key=lambda c: (c.attachment_id, c.position))
