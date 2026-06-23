"""Tiny markdown frontmatter parser, shared by slash/markdown commands and skills.

Supports a leading ``---`` block of simple ``key: value`` lines (no YAML dependency).
"""

from __future__ import annotations

__all__ = ["parse_frontmatter"]


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a leading ``---`` frontmatter block from the body.

    Returns ``(metadata, body)``. If there's no well-formed frontmatter, metadata is empty
    and body is the original text.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, text[end + 4 :].lstrip("\n")
