from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_telegraph_longtext.rendering import (  # noqa: E402
    derive_title,
    paginate_nodes,
    serialize_nodes,
    text_to_nodes,
)
from astrbot_plugin_telegraph_longtext.telegraph import (  # noqa: E402
    TelegraphClient,
    TelegraphError,
    format_link_message,
)
from astrbot_plugin_telegraph_longtext.title import generate_title  # noqa: E402


class TitleGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_session_provider_and_bounds_article(self):
        class Context:
            async def get_current_chat_provider_id(self, *, umo):
                self.umo = umo
                return "session-model"

            async def llm_generate(self, **kwargs):
                self.request = kwargs
                return SimpleNamespace(completion_text="标题：《股权收购的监管规则》")

        context = Context()
        title = await generate_title(context, "session", "文章" * 4000)
        self.assertEqual(title, "股权收购的监管规则")
        self.assertEqual(context.umo, "session")
        self.assertEqual(context.request["chat_provider_id"], "session-model")
        self.assertEqual(len(context.request["prompt"]), 6000)
        self.assertNotIn("tools", context.request)

    async def test_rejects_empty_multiline_and_overlong_responses(self):
        class Context:
            async def get_current_chat_provider_id(self, *, umo):
                return "model"

            async def llm_generate(self, **kwargs):
                return SimpleNamespace(completion_text=self.output)

        context = Context()
        for output in ("", "标题", "第一行\n第二行", "长" * 33, None):
            context.output = output
            with self.subTest(output=output):
                self.assertIsNone(await generate_title(context, "session", "正文"))

    async def test_model_error_propagates_to_caller(self):
        class Context:
            async def get_current_chat_provider_id(self, *, umo):
                raise RuntimeError("unavailable")

        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            await generate_title(Context(), "session", "正文")


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

    def test_title_preserves_numbers(self):
        self.assertEqual(derive_title("# 2026 年总结"), "2026 年总结")
        self.assertEqual(derive_title("# 3.14 是圆周率"), "3.14 是圆周率")
        self.assertEqual(derive_title("## **标题** 与 `代码`"), "标题 与 代码")

    def test_title_does_not_use_conversational_intro(self):
        text = "汪！这个问题超级硬核又好玩！" * 10
        self.assertEqual(derive_title(text, default="Gatery 长文"), "Gatery 长文")

    def test_title_prefers_explicit_main_heading(self):
        text = "汪！先说两句。\n\n## 第一关\n\n# 股权收购与监管规则\n\n正文"
        self.assertEqual(derive_title(text), "股权收购与监管规则")

    def test_title_ignores_code_quotes_and_long_headings(self):
        self.assertEqual(derive_title("```\n# 假标题\n```"), "AstrBot 长文")
        self.assertEqual(derive_title("> # 引用标题"), "AstrBot 长文")
        self.assertEqual(derive_title("# " + "长" * 33), "AstrBot 长文")
        self.assertEqual(derive_title("# " + "长" * 32), "长" * 32)

    def test_inline_formatting(self):
        nodes = text_to_nodes("**bold** and *italic* and ~~deleted~~")
        tags = [n["tag"] for n in nodes[0]["children"] if isinstance(n, dict)]
        self.assertEqual(tags, ["strong", "em", "s"])

    def test_code_and_math_are_not_rewritten(self):
        code = r"code $x^2$ and \frac{1}{2}"
        nodes = text_to_nodes(f"``{code}``\n\n```text\n{code}\n```")
        self.assertEqual(nodes[0]["children"][0]["children"], [code])
        self.assertEqual(nodes[1]["children"][0]["children"], [code + "\n"])

    def test_raw_html_is_literal(self):
        nodes = text_to_nodes("<script>alert(1)</script>")
        self.assertEqual(nodes[0]["tag"], "p")
        self.assertIn("<script>", "".join(nodes[0]["children"]))

    def test_tables_keep_cell_separators(self):
        nodes = text_to_nodes("| A | B |\n|---|---|\n| X | Y |")
        self.assertEqual(nodes[0]["children"], ["A", " | ", "B"])
        self.assertEqual(nodes[1]["children"], ["X", " | ", "Y"])

    def test_pages_measure_rendered_json(self):
        pages = paginate_nodes(text_to_nodes("**x**\n\n" * 7000))
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(serialize_nodes(p).encode()) <= 64000 for p in pages))
        self.assertEqual(sum(len(p) for p in pages), 7000)

    def test_split_code_preserves_content_and_tags(self):
        code = 'print("中文\\\\")\n' * 100
        pages = paginate_nodes(text_to_nodes(f"```python\n{code}```"), 180)
        self.assertGreater(len(pages), 1)
        parts = []
        for page in pages:
            self.assertLessEqual(len(serialize_nodes(page).encode()), 180)
            for node in page:
                self.assertEqual(node["tag"], "pre")
                self.assertEqual(node["children"][0]["tag"], "code")
                parts.extend(node["children"][0]["children"])
        self.assertEqual("".join(parts), code)

    def test_large_nested_list_preserves_wrappers(self):
        pages = paginate_nodes(text_to_nodes("- **" + "中文" * 200 + "**"), 180)
        for page in pages:
            self.assertLessEqual(len(serialize_nodes(page).encode()), 180)
            self.assertEqual(page[0]["tag"], "ul")
            self.assertEqual(page[0]["children"][0]["tag"], "li")

    def test_unsplittable_node_fails(self):
        with self.assertRaises(ValueError):
            paginate_nodes([{"tag": "img", "attrs": {"src": "https://x/" * 100}}], 100)

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
                "a" * 500,
                title="Test",
                author_name="AstrBot",
                max_content_bytes=100,
            )
            self.assertGreater(len(urls), 1)
            titles = [
                data["title"] for method, data in client.calls if method == "createPage"
            ]
            self.assertEqual(titles[0], f"Test (1/{len(urls)})")
            self.assertEqual(titles[-1], f"Test ({len(urls)}/{len(urls)})")
            for method, data in client.calls:
                if method == "createPage":
                    self.assertLessEqual(len(data["content"].encode()), 100)

    async def test_concurrent_requests_create_one_account(self):
        with tempfile.TemporaryDirectory() as directory:
            client = StubTelegraphClient(Path(directory) / "account.json")
            await asyncio.gather(
                *(
                    client.publish("hello", title="Test", author_name="AstrBot")
                    for _ in range(8)
                )
            )
            self.assertEqual(sum(m == "createAccount" for m, _ in client.calls), 1)

    async def test_invalid_token_does_not_create_another_account(self):
        class InvalidTokenClient(StubTelegraphClient):
            async def _request(self, method, data):
                self.calls.append((method, data))
                raise TelegraphError("ACCESS_TOKEN_INVALID")

        with tempfile.TemporaryDirectory() as directory:
            client = InvalidTokenClient(Path(directory) / "account.json")
            client.access_token = "invalid"
            with self.assertRaisesRegex(TelegraphError, "ACCESS_TOKEN_INVALID"):
                await client.publish("hello", title="Test", author_name="AstrBot")
            self.assertEqual([m for m, _ in client.calls], ["createPage"])

    async def test_corrupt_account_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account.json"
            path.write_text("broken")
            client = StubTelegraphClient(path)
            with self.assertRaises(json.JSONDecodeError):
                await client.publish("hello", title="Test", author_name="AstrBot")
            self.assertEqual(path.read_text(), "broken")
            self.assertEqual(client.calls, [])

    async def test_author_url_and_title_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            client = StubTelegraphClient(Path(directory) / "account.json")
            await client.publish(
                "hello",
                title="t" * 300,
                author_name="A",
                author_url="https://example.com",
            )
            data = client.calls[-1][1]
            self.assertEqual(len(data["title"]), 256)
            self.assertEqual(data["author_url"], "https://example.com")


if __name__ == "__main__":
    unittest.main()
