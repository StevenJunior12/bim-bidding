"""Document chunking with RAGFlow-inspired hierarchical merge.

Core logic (BULLET_PATTERN, bullets_category, Node, tree_merge) adapted from
RAGFlow (https://github.com/infiniflow/ragflow), Apache-2.0 licensed.

Pipeline:
1. Flatten parsed sections to individual lines
2. Detect document's bullet/heading pattern (RAGFlow bullets_category)
3. Build heading tree with depth control → tree_merge
   - Only split at target depth; deeper sub-items merge into parent
4. Post-process: semantic-split oversized chunks, merge tiny fragments
5. Fallback: semantic or fixed-size chunking when no structure detected
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass

from app.kb_parser import Section

logger = logging.getLogger(__name__)


@dataclass
class ChunkData:
    content: str
    heading_path: str  # e.g. "第1章 施工组织设计 > 1.1 工程概述"
    chunk_index: int


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
MIN_CHUNK_CHARS = 100   # chunks smaller than this get merged
MAX_CHUNK_CHARS = 1500  # chunks larger than this get semantic-split
TARGET_DEPTH = 2        # how many heading levels to split at

_FALLBACK_CHUNK_CHARS = 768
_FALLBACK_OVERLAP_CHARS = 75
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？\n])")
_MIN_SENTENCES_FOR_SEMANTIC = 3


# ===========================================================================
# RAGFlow core — BULLET_PATTERN, bullets_category, not_bullet, not_title,
#               Node, tree_merge
# ===========================================================================

# 5 pre-defined heading hierarchies for different document types.
# Within each list, index 0 = top level, increasing = deeper.
_BULLET_PATTERN = [
    # Pattern 0: Chinese legal / regulatory
    [
        r"第[零一二三四五六七八九十百0-9]+(分?编|部分)",
        r"第[零一二三四五六七八九十百0-9]+章",
        r"第[零一二三四五六七八九十百0-9]+节",
        r"第[零一二三四五六七八九十百0-9]+条",
        r"[\(（][零一二三四五六七八九十百]+[\)）]",
    ],
    # Pattern 1: Chinese numbered (most common for bidding docs)
    [
        r"第[0-9]+章",
        r"第[0-9]+节",
        r"[0-9]{,2}[\. 、]",
        r"[0-9]{,2}\.[0-9]{,2}[^a-zA-Z/%~-]",
        r"[0-9]{,2}\.[0-9]{,2}\.[0-9]{,2}",
        r"[0-9]{,2}\.[0-9]{,2}\.[0-9]{,2}\.[0-9]{,2}",
    ],
    # Pattern 2: Chinese mixed (chapter + bullet)
    [
        r"第[零一二三四五六七八九十百0-9]+章",
        r"第[零一二三四五六七八九十百0-9]+节",
        r"[零一二三四五六七八九十百]+[、]",
        r"[\(（][零一二三四五六七八九十百]+[\)）]",
        r"[\(（][0-9]{,2}[\)）]",
    ],
    # Pattern 3: English legal
    [
        r"PART (ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)",
        r"Chapter (I+V?|VI*|XI|IX|X)",
        r"Section [0-9]+",
        r"Article [0-9]+",
    ],
    # Pattern 4: Markdown
    [
        r"^#[^#]",
        r"^##[^#]",
        r"^###.*",
        r"^####.*",
        r"^#####.*",
        r"^######.*",
    ],
]


def _not_bullet(line: str) -> bool:
    """Filter out false positives — lines that look like bullets but aren't."""
    for p in [r"0", r"[0-9]+ +[0-9~个只-]", r"[0-9]+\.{2,}"]:
        if re.match(p, line):
            return True
    return False


def _bullets_category(sections: list[str]) -> int:
    """Detect which bullet pattern best matches the document.

    Returns the index into _BULLET_PATTERN, or -1 if none matches well.
    """
    hits = [0] * len(_BULLET_PATTERN)
    for i, patterns in enumerate(_BULLET_PATTERN):
        for sec in sections:
            sec = sec.strip()
            for p in patterns:
                if re.match(p, sec) and not _not_bullet(sec):
                    hits[i] += 1
                    break
    best, best_idx = 0, -1
    for i, h in enumerate(hits):
        if h > best:
            best_idx = i
            best = h
    return best_idx


def _not_title(txt: str) -> bool:
    """Return True if this text is unlikely to be a real title."""
    if re.match(r"第[零一二三四五六七八九十百0-9]+条", txt):
        return False
    if len(txt.split()) > 12 or (txt.find(" ") < 0 and len(txt) >= 32):
        return True
    return bool(re.search(r"[,;，。；！!]", txt))


class _Node:
    """Tree node for hierarchical document structure."""

    def __init__(self, level: int, depth: int = -1, texts: list[str] | None = None):
        self.level = level
        self.depth = depth
        self.texts: list[str] = texts or []
        self.children: list[_Node] = []

    def add_child(self, child: _Node) -> None:
        self.children.append(child)

    def add_text(self, text: str) -> None:
        self.texts.append(text)

    def get_texts(self) -> list[str]:
        return self.texts

    def get_level(self) -> int:
        return self.level

    def get_children(self) -> list[_Node]:
        return self.children

    def build_tree(self, lines: list[tuple[int, str]]) -> _Node:
        """Build tree from (level, text) pairs. depth limits splitting."""
        stack: list[_Node] = [self]
        for level, text in lines:
            if self.depth != -1 and level > self.depth:
                stack[-1].add_text(text)
                continue
            while len(stack) > 1 and level <= stack[-1].get_level():
                stack.pop()
            node = _Node(level=level, texts=[text])
            stack[-1].add_child(node)
            stack.append(node)
        return self

    def get_tree(self) -> list[str]:
        """DFS traversal → list of chunk strings (title path + body text)."""
        result: list[str] = []
        self._dfs(self, result, [])
        return result

    def _dfs(self, node: _Node, result: list[str], titles: list[str]) -> None:
        level = node.get_level()
        texts = node.get_texts()
        children = node.get_children()

        if level == 0 and texts:
            result.append("\n".join(titles + texts))

        if 1 <= level <= self.depth:
            path_titles = titles + texts
        else:
            path_titles = titles

        if level > self.depth and texts:
            result.append("\n".join(path_titles + texts))
        elif not children and (1 <= level <= self.depth):
            result.append("\n".join(path_titles))

        for c in children:
            self._dfs(c, result, path_titles)


def _tree_merge(
    bull: int,
    sections: list[tuple[str, str]],
    depth: int,
) -> list[str]:
    """RAGFlow tree_merge: build heading tree and extract depth-limited chunks.

    Args:
        bull: Index into _BULLET_PATTERN (from bullets_category).
        sections: List of (text, layout) tuples. layout may contain "title"/"head".
        depth: How many heading levels to split at. Deeper content merges into parent.

    Returns:
        List of chunk strings, each containing its title path + body text.
    """
    if not sections or bull < 0:
        return []
    if isinstance(sections[0], str):
        sections = [(s, "") for s in sections]

    # Filter out empty / noise lines
    sections = [
        (t, o) for t, o in sections
        if t and len(t.split("@")[0].strip()) > 1
        and not re.match(r"[0-9]+$", t.split("@")[0].strip())
    ]

    bullets_size = len(_BULLET_PATTERN[bull])

    def get_level(section: tuple[str, str]) -> tuple[int, str]:
        text, layout = section
        text = re.sub(r"　", " ", text).strip()
        for i, pat in enumerate(_BULLET_PATTERN[bull]):
            if re.match(pat, text.strip()):
                return i + 1, text
        if re.search(r"(title|head)", layout) and not _not_title(text):
            return bullets_size + 1, text
        return bullets_size + 2, text

    level_set: set[int] = set()
    lines: list[tuple[int, str]] = []
    for section in sections:
        level, text = get_level(section)
        if not text.strip("\n"):
            continue
        lines.append((level, text))
        level_set.add(level)

    if not lines:
        return []

    sorted_levels = sorted(level_set)
    if depth <= len(sorted_levels):
        target_level = sorted_levels[depth - 1]
    else:
        target_level = sorted_levels[-1]

    if target_level == bullets_size + 2:
        target_level = sorted_levels[-2] if len(sorted_levels) > 1 else sorted_levels[0]

    root = _Node(level=0, depth=target_level, texts=[])
    root.build_tree(lines)
    return [element for element in root.get_tree() if element]


# ===========================================================================
# Our chunking pipeline
# ===========================================================================

def chunk_sections(
    sections: list[Section],
    doc_filename: str = "",
    api_key: str | None = None,
    depth: int = TARGET_DEPTH,
) -> list[ChunkData]:
    """Split parsed sections into chunks.

    1. Flatten sections to individual lines
    2. Detect bullet pattern (RAGFlow bullets_category)
    3. tree_merge with depth control
    4. Post-process: semantic split oversized, merge tiny fragments
    5. Fallback: heading-based / semantic / fixed-size
    """
    if not sections:
        return []

    # Flatten to individual (text, layout) lines
    lines = _flatten_to_lines(sections)

    # Detect document's heading pattern
    bull = _bullets_category([t for t, _ in lines])

    chunks: list[ChunkData] = []

    if bull >= 0:
        # RAGFlow tree_merge — the main strategy
        chunk_texts = _tree_merge(bull, lines, depth)
        if chunk_texts:
            chunks = [_make_chunk(t, i) for i, t in enumerate(chunk_texts)]
            logger.info(
                "chunk_sections: tree_merge(bull=%d, depth=%d) → %d chunks",
                bull, depth, len(chunks),
            )

    # Fallback: if tree_merge didn't work, use heading-based or semantic
    if not chunks:
        has_headings = any(s.heading_level > 0 for s in sections)
        if has_headings:
            chunks = _chunk_by_headings(sections, doc_filename)
        elif api_key:
            sem = _chunk_by_semantic_fallback(sections, doc_filename, api_key)
            if sem:
                chunks = sem
        if not chunks:
            chunks = _chunk_by_fixed_size(sections, doc_filename)

    # Post-process
    chunks = _split_oversized_chunks(chunks, api_key)
    chunks = _merge_small_chunks(chunks)

    for i, c in enumerate(chunks):
        c.chunk_index = i
    return chunks


# ---------------------------------------------------------------------------
# Flatten parser output to individual lines
# ---------------------------------------------------------------------------

def _flatten_to_lines(sections: list[Section]) -> list[tuple[str, str]]:
    """Convert Section list to flat (text, layout) tuples.

    Heading text is marked as "title" so tree_merge can use both
    bullet-pattern detection AND parser-detected heading info.
    """
    lines: list[tuple[str, str]] = []
    for s in sections:
        if s.heading_level > 0 and s.heading_text.strip():
            lines.append((s.heading_text.strip(), "title"))
        for ln in s.content.split("\n"):
            ln = ln.strip()
            if ln:
                lines.append((ln, ""))
    return lines


def _make_chunk(text: str, index: int) -> ChunkData:
    """Convert a chunk string (title path + body) to ChunkData."""
    lines = text.split("\n")
    # First line is the deepest heading in the path
    heading_path = lines[0].strip() if lines else ""
    return ChunkData(content=text, heading_path=heading_path, chunk_index=index)


# ---------------------------------------------------------------------------
# Fallback: heading-based chunking (original logic)
# ---------------------------------------------------------------------------

def _chunk_by_headings(sections: list[Section], doc_filename: str) -> list[ChunkData]:
    chunks: list[ChunkData] = []
    idx = 0
    heading_stack: list[tuple[int, str]] = []

    for section in sections:
        if section.heading_level > 0:
            while heading_stack and heading_stack[-1][0] >= section.heading_level:
                heading_stack.pop()
            heading_stack.append((section.heading_level, section.heading_text))

        path_parts = [h[1] for h in heading_stack]
        heading_path = " > ".join(path_parts) if path_parts else doc_filename

        if section.heading_level > 0:
            content = section.heading_text
            if section.content.strip():
                content += "\n" + section.content.strip()
        else:
            content = section.content.strip()
            if not content:
                continue

        chunks.append(ChunkData(content=content, heading_path=heading_path, chunk_index=idx))
        idx += 1
    return chunks


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def _merge_small_chunks(chunks: list[ChunkData]) -> list[ChunkData]:
    if len(chunks) <= 1:
        return chunks
    merged: list[ChunkData] = []
    i = 0
    while i < len(chunks):
        cur = chunks[i]
        while len(cur.content) < MIN_CHUNK_CHARS and i + 1 < len(chunks):
            nxt = chunks[i + 1]
            cur = ChunkData(
                content=cur.content + "\n" + nxt.content,
                heading_path=cur.heading_path,
                chunk_index=cur.chunk_index,
            )
            i += 1
        merged.append(cur)
        i += 1
    return merged


def _split_oversized_chunks(chunks: list[ChunkData], api_key: str | None) -> list[ChunkData]:
    result: list[ChunkData] = []
    for chunk in chunks:
        if len(chunk.content) <= MAX_CHUNK_CHARS:
            result.append(chunk)
            continue
        sub = _semantic_split_text(chunk.content, chunk.heading_path, api_key)
        if sub:
            result.extend(sub)
        else:
            result.extend(_fixed_split_text(chunk.content, chunk.heading_path))
    return result


# ---------------------------------------------------------------------------
# Semantic chunking (for oversized chunks / no-structure fallback)
# ---------------------------------------------------------------------------

def _chunk_by_semantic_fallback(
    sections: list[Section],
    doc_filename: str,
    api_key: str,
) -> list[ChunkData] | None:
    all_text = "\n".join(
        (s.heading_text + "\n" + s.content if s.heading_text else s.content)
        for s in sections
    ).strip()
    if not all_text:
        return None
    return _semantic_split_text(all_text, doc_filename or "(未检测到标题)", api_key)


def _semantic_split_text(
    text: str,
    heading_path: str,
    api_key: str | None,
) -> list[ChunkData] | None:
    if not api_key:
        return None
    sentences = _split_sentences(text)
    if len(sentences) < _MIN_SENTENCES_FOR_SEMANTIC:
        return None
    from app.kb_embedding import embed_texts
    try:
        embeddings = embed_texts(sentences, api_key=api_key)
    except Exception:
        return None
    if len(embeddings) != len(sentences):
        return None

    sims = [_cosine_similarity(embeddings[i], embeddings[i + 1]) for i in range(len(embeddings) - 1)]
    if not sims:
        return None

    mean_sim = sum(sims) / len(sims)
    std_sim = math.sqrt(sum((s - mean_sim) ** 2 for s in sims) / len(sims))
    threshold = mean_sim - std_sim

    chunks: list[ChunkData] = []
    group: list[str] = [sentences[0]]

    for i, sim in enumerate(sims):
        group.append(sentences[i + 1])
        current_len = sum(len(s) for s in group)

        should_break = False
        if sim < threshold and current_len >= MIN_CHUNK_CHARS:
            should_break = True
        elif current_len >= MAX_CHUNK_CHARS:
            should_break = True

        if should_break:
            chunks.append(ChunkData(content="".join(group).strip(), heading_path=heading_path, chunk_index=0))
            group = []

    if group:
        tail = "".join(group).strip()
        if chunks and len(tail) < MIN_CHUNK_CHARS:
            chunks[-1] = ChunkData(
                content=chunks[-1].content + "\n" + tail,
                heading_path=heading_path, chunk_index=0,
            )
        else:
            chunks.append(ChunkData(content=tail, heading_path=heading_path, chunk_index=0))

    return chunks if chunks else None


# ---------------------------------------------------------------------------
# Fixed-size fallback
# ---------------------------------------------------------------------------

def _chunk_by_fixed_size(sections: list[Section], doc_filename: str) -> list[ChunkData]:
    all_text = "\n".join(
        (s.heading_text + "\n" + s.content if s.heading_text else s.content)
        for s in sections
    ).strip()
    if not all_text:
        return []
    return _fixed_split_text(all_text, doc_filename or "(未检测到标题)")


def _fixed_split_text(text: str, heading_path: str) -> list[ChunkData]:
    chunks: list[ChunkData] = []
    idx = 0
    start = 0
    while start < len(text):
        end = start + _FALLBACK_CHUNK_CHARS
        piece = text[start:end].strip()
        if piece:
            chunks.append(ChunkData(content=piece, heading_path=heading_path, chunk_index=idx))
            idx += 1
        start += _FALLBACK_CHUNK_CHARS - _FALLBACK_OVERLAP_CHARS
        if start >= len(text):
            break
    return chunks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT_RE.split(text)
    raw = [p.strip() for p in parts if p.strip()]
    merged: list[str] = []
    for s in raw:
        if merged and len(s) < 10:
            merged[-1] += s
        else:
            merged.append(s)
    return merged


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
