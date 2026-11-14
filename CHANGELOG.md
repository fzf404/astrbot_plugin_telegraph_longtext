# Changelog

## 1.2.2 - 2026-11-14

- Generate concise article titles using the current session's chat model.
- Fall back to a Markdown heading or configured title if generation fails.

## 1.2.1 - 2026-11-12

- Use explicit Markdown headings up to 32 characters as page titles.
- Fall back to the configured title instead of extracting conversational prose.

## 1.2.0 - 2026-11-12

- Render Markdown with markdown-it-py, including inline formatting and tables.
- Generate titles from parsed content and support author links.
- Paginate serialized content within 64 KB while preserving code and list tags.
- Preserve existing accounts on token errors and prevent concurrent account creation.
- Keep code, raw HTML and mathematical notation free of lossy conversions.

## 1.1.3 - 2026-07-27

- Adjust the default automatic publishing threshold from 1000 to 800 characters.

## 1.1.2 - 2026-07-27

- Raise the default automatic publishing threshold from 200 to 1000 characters.

## 1.1.1 - 2026-07-25

- Change the default automatic publishing threshold from 150 to 200 characters.

## 1.1.0 - 2026-07-25

- Add independent WebUI configuration and internationalized labels.
- Replace blocking HTTP calls with an asynchronous `aiohttp` client.
- Persist and reuse the automatically created Telegraph account.
- Split oversized content into multiple Telegraph pages.
- Preserve non-text message components and original text on failure.
- Render common Markdown blocks as readable Telegraph content.
- Add automated tests, Ruff checks, and GitHub Actions CI.

## 1.0.0 - 2026-07-23

- Initial private deployment.
