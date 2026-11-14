from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

MAX_CONTENT_BYTES = 64_000
TelegraphNode = str | dict[str, Any]
_TAGS = {
    **dict.fromkeys(("h1", "h2"), "h3"),
    **dict.fromkeys(("h3", "h4", "h5", "h6"), "h4"),
    "del": "s",
    "tr": "p",
    **{
        tag: tag
        for tag in (
            "p",
            "br",
            "hr",
            "blockquote",
            "pre",
            "code",
            "strong",
            "em",
            "s",
            "a",
            "img",
            "ul",
            "ol",
            "li",
        )
    },
}
_VOID_TAGS = {"br", "hr", "img"}


@lru_cache(maxsize=1)
def _markdown_parser() -> MarkdownIt:
    return MarkdownIt("commonmark", {"html": False, "breaks": True}).enable(
        ["strikethrough", "table"]
    )


class _NodeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[TelegraphNode] = []
        self.stack: list[tuple[str, list[TelegraphNode] | None]] = []
        self.cells = 0

    def _children(self) -> list[TelegraphNode]:
        for _, children in reversed(self.stack):
            if children is not None:
                return children
        return self.nodes

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.cells = 0
        if tag in ("td", "th"):
            if self.cells:
                self._children().append(" | ")
            self.cells += 1
        mapped = _TAGS.get(tag)
        attributes = {}
        for key, value in attrs:
            allowed = (
                {"http", "https"}
                if key == "src"
                else {
                    "http",
                    "https",
                    "mailto",
                    "tg",
                }
            )
            if key in ("href", "src") and value:
                try:
                    safe = urlsplit(value).scheme.lower() in allowed
                except ValueError:
                    safe = False
                if safe:
                    attributes[key] = value
        if mapped is None or (mapped in ("a", "img") and not attributes):
            if tag not in _VOID_TAGS:
                self.stack.append((tag, None))
            return
        node: dict[str, Any] = {"tag": mapped}
        if attributes:
            node["attrs"] = attributes
        self._children().append(node)
        if tag not in _VOID_TAGS:
            node["children"] = []
            self.stack.append((tag, node["children"]))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        parent = next(
            (tag for tag, children in reversed(self.stack) if children is not None),
            None,
        )
        if not data.strip() and (
            parent in {None, "ul", "ol", "blockquote"}
            or ("\n" in data and parent not in {"pre", "code"})
        ):
            return
        self._children().append(data)


def text_to_nodes(text: str) -> list[TelegraphNode]:
    """Render Markdown; do not interpret raw HTML or convert mathematical notation."""
    builder = _NodeBuilder()
    builder.feed(_markdown_parser().render(text))
    builder.close()
    return builder.nodes or [{"tag": "p", "children": [text]}]


def derive_title(
    text: str,
    default: str = "AstrBot 长文",
    limit: int = 32,
) -> str:
    tokens = _markdown_parser().parse(text)
    headings: list[tuple[int, str]] = []
    for index, opening in enumerate(tokens[:-1]):
        if opening.type != "heading_open" or opening.level != 0:
            continue
        token = tokens[index + 1]
        if token.type != "inline" or not token.children:
            continue
        title = "".join(
            child.content
            if child.type in {"text", "code_inline", "image"}
            else " "
            if child.type in {"softbreak", "hardbreak"}
            else ""
            for child in token.children
        ).strip()
        if title and len(title) <= limit:
            headings.append((int(opening.tag[1:]), title))
    return (
        min(headings, key=lambda heading: heading[0])[1]
        if headings
        else (default.strip() or "AstrBot 长文")
    )


def serialize_nodes(nodes: Sequence[TelegraphNode]) -> str:
    return json.dumps(nodes, ensure_ascii=False, separators=(",", ":"))


def paginate_nodes(
    nodes: Sequence[TelegraphNode],
    max_bytes: int = MAX_CONTENT_BYTES,
) -> list[list[TelegraphNode]]:
    """Measure serialized UTF-8 JSON and retain enclosing tags on every page."""
    if not 64 <= max_bytes <= MAX_CONTENT_BYTES:
        raise ValueError(f"max_bytes must be between 64 and {MAX_CONTENT_BYTES}")
    return _pack_nodes(nodes, max_bytes)


def _pack_nodes(
    nodes: Sequence[TelegraphNode],
    budget: int,
) -> list[list[TelegraphNode]]:
    pages: list[list[TelegraphNode]] = []
    page: list[TelegraphNode] = []
    size = 2
    for node in nodes:
        parts = _split_node(node, budget - 2)
        for part in parts:
            part_size = len(serialize_nodes([part]).encode("utf-8")) - 2
            if page and size + 1 + part_size > budget:
                pages.append(page)
                page, size = [], 2
            size += part_size + bool(page)
            page.append(part)
    if page:
        pages.append(page)
    return pages


def _split_node(node: TelegraphNode, budget: int) -> list[TelegraphNode]:
    if len(serialize_nodes([node]).encode("utf-8")) - 2 <= budget:
        return [node]
    if isinstance(node, str):
        if len(node) < 2:
            raise ValueError("A character cannot fit within the Telegraph page limit")
        middle = len(node) // 2
        return _split_node(node[:middle], budget) + _split_node(node[middle:], budget)
    children = node.get("children", [])
    if not children:
        raise ValueError("A node cannot fit within the Telegraph page limit")
    shell = {**node, "children": []}
    overhead = len(serialize_nodes([shell]).encode("utf-8")) - 2
    child_budget = budget - overhead + 2
    return [{**node, "children": page} for page in _pack_nodes(children, child_budget)]
