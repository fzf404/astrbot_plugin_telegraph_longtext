from __future__ import annotations

import traceback

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

from .telegraph import TelegraphClient, format_link_message

PLUGIN_NAME = "astrbot_plugin_telegraph_longtext"


class TelegraphLongTextPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        self.client = TelegraphClient(
            access_token=str(config.get("access_token", "")),
            token_file=data_dir / "account.json",
            timeout_seconds=self._as_int("timeout_seconds", 20, minimum=5),
            retries=self._as_int("retries", 2, minimum=0),
        )

    def _as_int(self, key: str, default: int, *, minimum: int) -> int:
        try:
            return max(int(self.config.get(key, default)), minimum)
        except (TypeError, ValueError):
            return default

    @filter.on_decorating_result()
    async def replace_long_text(self, event: AstrMessageEvent) -> None:
        if not bool(self.config.get("enabled", True)):
            return

        result = event.get_result()
        if result is None or not result.chain:
            return

        leading_plain: list[Comp.Plain] = []
        for component in result.chain:
            if not isinstance(component, Comp.Plain):
                break
            leading_plain.append(component)

        text = "\n\n".join(component.text for component in leading_plain).strip()
        threshold = self._as_int("threshold_chars", 1000, minimum=50)
        if not text or len(text) <= threshold:
            return

        try:
            urls = await self.client.publish(
                text,
                title=str(self.config.get("page_title", "AstrBot 长文")),
                author_name=str(self.config.get("author_name", "AstrBot")),
            )
        except Exception:
            logger.error(traceback.format_exc())
            logger.error("Telegraph 长文发布失败，已保留原始文本。")
            if str(self.config.get("failure_mode", "keep_text")) == "keep_text":
                result.use_t2i_ = False
            return

        template = str(
            self.config.get(
                "link_message",
                "内容较长，已发布至 Telegraph：\n{url}",
            )
        )
        link_component = Comp.Plain(format_link_message(template, urls))
        result.chain = [link_component, *result.chain[len(leading_plain) :]]
        result.use_t2i_ = False
        logger.info("长文已发布至 Telegraph，共 %d 页。", len(urls))

    @filter.command("telegraph_test")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def telegraph_test(self, event: AstrMessageEvent):
        """测试 Telegraph 连通性与插件配置。"""
        try:
            urls = await self.client.publish(
                "AstrBot Telegraph 插件连接测试成功。",
                title=str(self.config.get("page_title", "AstrBot 长文")),
                author_name=str(self.config.get("author_name", "AstrBot")),
            )
            yield event.plain_result(f"Telegraph 测试成功：\n{urls[0]}")
        except Exception as exc:
            logger.error(traceback.format_exc())
            yield event.plain_result(f"Telegraph 测试失败：{exc}")

    async def terminate(self) -> None:
        await self.client.close()
