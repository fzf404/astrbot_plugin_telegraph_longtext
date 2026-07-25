from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from telegraph import TelegraphClient, format_link_message, split_text, text_to_nodes


class StubTelegraphClient(TelegraphClient):
    def __init__(self, token_file: Path):
        super().__init__(token_file=token_file, retries=0)
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def _request(self, method: str, data: dict[str, str]):
        self.calls.append((method, data))
        if method == "createAccount":
            return {"access_token": "saved-token"}
        page_count = sum(name == "createPage" for name, _ in self.calls)
        return {"url": f"https://telegra.ph/test-{page_count}"}


class TelegraphFormattingTests(unittest.TestCase):
    def test_markdown_blocks_are_converted(self):
        nodes = text_to_nodes(
            "# Title\n\n- one\n- two\n\n> quote\n\n```\nprint('ok')\n```"
        )
        self.assertEqual(
            [node["tag"] for node in nodes], ["h3", "ul", "blockquote", "pre"]
        )

    def test_split_text_respects_utf8_budget(self):
        chunks = split_text("中文" * 100, max_bytes=30)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.encode("utf-8")) <= 30 for chunk in chunks))
        self.assertEqual("".join(chunks), "中文" * 100)

    def test_link_template_supports_multiple_pages(self):
        message = format_link_message(
            "Read:\n{url}",
            ["https://telegra.ph/one", "https://telegra.ph/two"],
        )
        self.assertEqual(
            message,
            "Read:\nhttps://telegra.ph/one\nhttps://telegra.ph/two",
        )


class TelegraphClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_account_is_persisted_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "account.json"
            first = StubTelegraphClient(token_file)
            urls = await first.publish("hello", title="Test", author_name="AstrBot")

            self.assertEqual(urls, ["https://telegra.ph/test-1"])
            self.assertTrue(token_file.exists())
            self.assertEqual(first.calls[0][0], "createAccount")

            second = StubTelegraphClient(token_file)
            await second.publish("again", title="Test", author_name="AstrBot")
            self.assertEqual([name for name, _ in second.calls], ["createPage"])

    async def test_oversized_text_creates_multiple_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            client = StubTelegraphClient(Path(directory) / "account.json")
            urls = await client.publish(
                "a" * 50,
                title="Test",
                author_name="AstrBot",
                max_chunk_bytes=10,
            )
            self.assertEqual(len(urls), 5)
            titles = [
                data["title"] for method, data in client.calls if method == "createPage"
            ]
            self.assertEqual(titles[0], "Test (1/5)")
            self.assertEqual(titles[-1], "Test (5/5)")


if __name__ == "__main__":
    unittest.main()
