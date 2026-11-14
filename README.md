# AstrBot Telegraph Long Text

![Telegraph 长文本插件图标](https://raw.githubusercontent.com/fzf404/astrbot_plugin_telegraph_longtext/main/logo.png)

将 AstrBot 的超长回复自动发布到 [Telegraph](https://telegra.ph/)，并在聊天中发送轻量、易读的页面链接。

## 功能

- 按字符数阈值自动转换长回复
- 在 AstrBot WebUI 中直接配置，无需修改代码
- 支持标题、作者、链接提示语和失败策略
- 自动创建并持久化 Telegraph 账户
- 内容超过 Telegraph 单页限制时自动分页
- 保留回复中的图片、文件等非文本组件
- 支持 Markdown 标题、列表、引用、代码、加粗、链接、图片和表格
- 按渲染后 JSON 大小分页，跨页保留代码和列表结构
- 全异步网络请求，带超时和自动重试
- 发布失败时默认保留原始文本

## 安装

在 AstrBot WebUI 的插件市场中搜索“Telegraph 长文本”，也可以访问 [AstrBot 插件市场](https://cloud.astrbot.app/plugin/fzf404/astrbot_plugin_telegraph_longtext)查看插件详情。

也可以在插件管理页面点击右下角 `+`，选择“从链接安装”，填入：

```text
https://github.com/fzf404/astrbot_plugin_telegraph_longtext
```

也可以放入 AstrBot 插件目录：

```bash
cd AstrBot/data/plugins
git clone https://github.com/fzf404/astrbot_plugin_telegraph_longtext
```

重载或重启 AstrBot 后即可使用。

## 配置

进入 AstrBot WebUI 的“插件”页面，打开“Telegraph 长文本”的配置。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| 启用自动转 Telegraph | 开启 | 插件总开关 |
| 自动转换字数 | `800` | 纯文本超过此长度时自动发布，最小值为 50 |
| 使用模型生成标题 | 开启 | 使用当前会话模型生成短标题，每篇文章增加一次模型调用；最多发送正文前 6000 字 |
| Telegraph 页面标题 | `AstrBot 长文` | 关闭标题生成时使用；生成失败时优先使用正文标题，再使用此固定标题 |
| Telegraph 作者名 | `AstrBot` | 页面作者 |
| 作者链接 | 留空 | 点击作者名时打开的链接 |
| 链接消息模板 | `内容较长...{url}` | `{url}` 会替换为页面链接 |
| 发布失败时 | 保留原始文本 | 也可继续使用 AstrBot 文转图 |
| Telegraph Access Token | 留空 | 留空时会自动创建并持久化账户 |
| 请求超时 | `20` 秒 | Telegraph 单次请求超时，最小值为 5 秒 |
| 失败重试次数 | `2` | 临时网络错误的重试次数 |

管理员可以发送 `/telegraph_test` 检查 Telegraph 连通性。

## 工作方式

插件使用 AstrBot 官方的 `on_decorating_result` 发送前钩子，只处理消息链开头连续的纯文本组件。超过阈值后，文本会被替换为 Telegraph 链接，后续图片或文件组件仍会保留。

流式输出时，平台可能已经显示正文，无法保证长文本转换效果。需要稳定转换时，建议关闭流式输出。

Markdown 表格会转为逐行文本；LaTeX 不会渲染为公式，部分符号可能受 Markdown 转义规则影响。原始 HTML 作为文本显示。

## 隐私

被转换的内容会发送到 Telegraph 并生成公开链接。请不要用它发布密码、Token、个人隐私或其他敏感信息。

启用模型生成标题时，正文前 6000 字还会发送给当前会话使用的模型服务。

自动创建的 Telegraph Access Token 保存在 AstrBot 的：

```text
data/plugin_data/astrbot_plugin_telegraph_longtext/account.json
```

它不会写入插件仓库，升级插件时也不会丢失。

已有 Token 无效或账户文件损坏时，插件保留原文并报告错误，不会自动创建另一个账号。请先检查 Token 或恢复原账户文件。

## 开发

要求 AstrBot `>=4.26.7,<5`（Python 3.12+）。

```bash
pip install -r requirements.txt ruff
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
```

## License

[MIT](https://github.com/fzf404/astrbot_plugin_telegraph_longtext/blob/main/LICENSE)
