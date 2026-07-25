from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import aiohttp

API_BASE = "https://api.telegra.ph"
DEFAULT_MAX_CHUNK_BYTES = 48_000

TelegraphNode = str | dict[str, Any]
TokenSaver = Callable[[str], Awaitable[None]]


class TelegraphError(RuntimeError):
    """Raised when Telegraph rejects a request or returns malformed data."""


def _text_node(tag: str, text: str) -> dict[str, Any]:
    return {"tag": tag, "children": [text]}


def text_to_nodes(text: str) -> list[TelegraphNode]:
    """Convert common plain-text/Markdown blocks into Telegraph nodes."""
    nodes: list[TelegraphNode] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_tag: str | None = None
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if not paragraph:
            return
        children: list[TelegraphNode] = []
        for index, line in enumerate(paragraph):
            if index:
                children.append({"tag": "br"})
            children.append(line)
        nodes.append({"tag": "p", "children": children})
        paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if not list_items or list_tag is None:
            return
        nodes.append(
            {
                "tag": list_tag,
                "children": [{"tag": "li", "children": [item]} for item in list_items],
            }
        )
        list_items.clear()
        list_tag = None

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            flush_list()
            if in_code:
                nodes.append(_text_node("pre", "\n".join(code_lines)))
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            flush_paragraph()
            flush_list()
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            flush_list()
            tag = "h3" if len(heading.group(1)) <= 2 else "h4"
            nodes.append(_text_node(tag, heading.group(2)))
            continue

        if stripped.startswith("> "):
            flush_paragraph()
            flush_list()
            nodes.append(_text_node("blockquote", stripped[2:]))
            continue

        unordered = re.match(r"^[-*+]\s+(.+)$", stripped)
        ordered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if unordered or ordered:
            flush_paragraph()
            next_tag = "ul" if unordered else "ol"
            if list_tag and list_tag != next_tag:
                flush_list()
            list_tag = next_tag
            list_items.append((unordered or ordered).group(1))
            continue

        flush_list()
        paragraph.append(stripped)

    if in_code and code_lines:
        nodes.append(_text_node("pre", "\n".join(code_lines)))
    flush_paragraph()
    flush_list()
    return nodes or [_text_node("p", text)]


def split_text(text: str, max_bytes: int = DEFAULT_MAX_CHUNK_BYTES) -> list[str]:
    """Split text on natural boundaries while respecting a UTF-8 byte budget."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_bytes = 0
    blocks = re.split(r"(\n{2,})", normalized)

    def flush() -> None:
        nonlocal current_bytes
        if current:
            chunks.append("".join(current).strip())
            current.clear()
            current_bytes = 0

    for block in blocks:
        if not block:
            continue
        remaining = block
        while remaining:
            room = max_bytes - current_bytes
            encoded = remaining.encode("utf-8")
            if len(encoded) <= room:
                current.append(remaining)
                current_bytes += len(encoded)
                break

            if current:
                flush()
                continue

            byte_count = 0
            split_at = 0
            for index, char in enumerate(remaining):
                char_bytes = len(char.encode("utf-8"))
                if byte_count + char_bytes > max_bytes:
                    break
                byte_count += char_bytes
                split_at = index + 1
            if split_at == 0:
                split_at = 1
            current.append(remaining[:split_at])
            current_bytes = len(remaining[:split_at].encode("utf-8"))
            remaining = remaining[split_at:]
            flush()

    flush()
    return chunks


class TelegraphClient:
    def __init__(
        self,
        *,
        access_token: str = "",
        token_file: Path | None = None,
        timeout_seconds: int = 20,
        retries: int = 2,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.access_token = access_token.strip()
        self.token_file = token_file
        self.timeout_seconds = max(timeout_seconds, 1)
        self.retries = max(retries, 0)
        self._session = session
        self._owns_session = session is None
        self._account_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": "AstrBot-Telegraph-LongText/1.1"},
            )
        return self._session

    async def _request(self, method: str, data: dict[str, str]) -> dict[str, Any]:
        session = await self._get_session()
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                async with session.post(f"{API_BASE}/{method}", data=data) as response:
                    payload = await response.json(content_type=None)
                    if response.status >= 500:
                        raise TelegraphError(f"Telegraph HTTP {response.status}")
                    if not payload.get("ok"):
                        error = payload.get("error", "unknown Telegraph API error")
                        raise TelegraphError(str(error))
                    result = payload.get("result")
                    if not isinstance(result, dict):
                        raise TelegraphError("Telegraph returned an invalid result")
                    return result
            except (TimeoutError, aiohttp.ClientError, TelegraphError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                await asyncio.sleep(0.5 * (2**attempt))
        raise TelegraphError(f"Telegraph request failed: {last_error}") from last_error

    def _load_saved_token(self) -> str:
        if not self.token_file or not self.token_file.exists():
            return ""
        try:
            payload = json.loads(self.token_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        token = payload.get("access_token", "")
        return token.strip() if isinstance(token, str) else ""

    def _save_token(self, token: str) -> None:
        if not self.token_file:
            return
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.token_file.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"access_token": token}, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.token_file)

    async def ensure_account(self, author_name: str) -> str:
        if self.access_token:
            return self.access_token

        async with self._account_lock:
            if self.access_token:
                return self.access_token
            saved_token = await asyncio.to_thread(self._load_saved_token)
            if saved_token:
                self.access_token = saved_token
                return saved_token

            account = await self._request(
                "createAccount",
                {
                    "short_name": author_name[:32] or "AstrBot",
                    "author_name": author_name[:128] or "AstrBot",
                },
            )
            token = account.get("access_token")
            if not isinstance(token, str) or not token:
                raise TelegraphError(
                    "Telegraph account did not include an access token"
                )
            self.access_token = token
            await asyncio.to_thread(self._save_token, token)
            return token

    async def publish(
        self,
        text: str,
        *,
        title: str,
        author_name: str,
        max_chunk_bytes: int = DEFAULT_MAX_CHUNK_BYTES,
    ) -> list[str]:
        token = await self.ensure_account(author_name)
        chunks = split_text(text, max_chunk_bytes)
        if not chunks:
            raise TelegraphError("Cannot publish empty text")

        urls: list[str] = []
        total = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            page_title = title.strip() or "AstrBot Long Text"
            if total > 1:
                page_title = f"{page_title} ({index}/{total})"
            page = await self._request(
                "createPage",
                {
                    "access_token": token,
                    "title": page_title[:256],
                    "author_name": author_name[:128] or "AstrBot",
                    "content": json.dumps(text_to_nodes(chunk), ensure_ascii=False),
                    "return_content": "false",
                },
            )
            url = page.get("url")
            if not isinstance(url, str) or not url.startswith("https://telegra.ph/"):
                raise TelegraphError("Telegraph page did not include a valid URL")
            urls.append(url)
        return urls


def format_link_message(template: str, urls: Sequence[str]) -> str:
    links = "\n".join(urls)
    if "{url}" in template:
        return template.replace("{url}", links)
    return f"{template.rstrip()}\n{links}"
