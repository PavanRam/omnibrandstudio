from __future__ import annotations


def _split_paragraphs(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    return paragraphs or [cleaned]


def _split_long_paragraph(para: str, chunk_size: int, overlap: int) -> list[str]:
    out: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(para):
        piece = para[start : start + chunk_size].strip()
        if piece:
            out.append(piece)
        start += step
    return out


def _flush_overflow(text: str, chunk_size: int, overlap: int) -> tuple[list[str], str]:
    emitted: list[str] = []
    overflow = text
    step = max(1, chunk_size - overlap)
    while len(overflow) > chunk_size:
        piece = overflow[:chunk_size].strip()
        if piece:
            emitted.append(piece)
        overflow = overflow[step:]
    return emitted, overflow.strip()


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    """Paragraph-aware chunking with fixed char-window fallback.

    The implementation prefers paragraph boundaries but still guarantees
    progress with overlap when paragraphs exceed chunk_size.
    """
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = para if not current else f"{current}\n\n{para}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if not current:
            chunks.extend(_split_long_paragraph(para, chunk_size, overlap))
            continue

        chunks.append(current)
        tail = current[-overlap:] if overlap > 0 else ""
        combined = f"{tail}\n\n{para}".strip()
        emitted, current = _flush_overflow(combined, chunk_size, overlap)
        chunks.extend(emitted)

    if current.strip():
        chunks.append(current.strip())

    return chunks
