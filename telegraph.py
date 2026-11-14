from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import aiohttp

from .rendering import (
    MAX_CONTENT_BYTES,
    derive_title,
    paginate_nodes,
    serialize_nodes,
    text_to_nodes,
)

API_BASE = "https://api.telegra.ph"


class TelegraphError(RuntimeError):
    """Raised when Telegraph rejects a request or returns malformed data."""


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
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                headers={"User-Agent": "AstrBot-Telegraph-LongText/1.2"},
            )
        return self._session

    async def _request(self, method: str, data: dict[str, str]) -> dict[str, Any]:
        session = await self._get_session()
        for attempt in range(self.retries + 1):
            try:
                async with session.post(f"{API_BASE}/{method}", data=data) as response:
                    if response.status >= 500:
                        raise aiohttp.ClientError(f"Telegraph HTTP {response.status}")
                    payload = await response.json(content_type=None)
                    if not isinstance(payload, dict):
                        raise TelegraphError("Telegraph returned an invalid response")
                    if not payload.get("ok"):
                        raise TelegraphError(str(payload.get("error", "Unknown error")))
                    result = payload.get("result")
                    if not isinstance(result, dict):
                        raise TelegraphError("Telegraph returned an invalid result")
                    return result
            except (TimeoutError, aiohttp.ClientError) as exc:
                if attempt >= self.retries:
                    raise TelegraphError("Telegraph network request failed") from exc
                await asyncio.sleep(0.5 * (2**attempt))
        raise AssertionError("Unreachable request state")

    def _load_saved_token(self) -> str:
        if not self.token_file or not self.token_file.exists():
            return ""
        payload = json.loads(self.token_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TelegraphError("Invalid saved Telegraph account")
        token = payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise TelegraphError("Saved Telegraph account has no access token")
        return token.strip()

    def _save_token(self, token: str) -> None:
        if not self.token_file:
            return
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.token_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({"access_token": token}), encoding="utf-8")
        temporary.chmod(0o600)
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
                    "short_name": author_name.strip()[:32] or "AstrBot",
                    "author_name": author_name[:128] or "AstrBot",
                },
            )
            token = account.get("access_token")
            if not isinstance(token, str) or not token:
                raise TelegraphError(
                    "Telegraph account did not include an access token"
                )
            await asyncio.to_thread(self._save_token, token)
            self.access_token = token
            return token

    async def publish(
        self,
        text: str,
        *,
        title: str,
        author_name: str,
        author_url: str = "",
        max_content_bytes: int = MAX_CONTENT_BYTES,
    ) -> list[str]:
        if not text.strip():
            raise TelegraphError("Cannot publish empty text")
        pages = paginate_nodes(text_to_nodes(text), max_content_bytes)
        token = await self.ensure_account(author_name)
        urls: list[str] = []
        for index, nodes in enumerate(pages, start=1):
            suffix = f" ({index}/{len(pages)})" if len(pages) > 1 else ""
            page_title = (title.strip() or derive_title(text))[: 256 - len(suffix)]
            data = {
                "access_token": token,
                "title": page_title + suffix,
                "author_name": author_name[:128] or "AstrBot",
                "content": serialize_nodes(nodes),
                "return_content": "false",
            }
            if author_url.strip():
                data["author_url"] = author_url.strip()[:512]
            page = await self._request("createPage", data)
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
