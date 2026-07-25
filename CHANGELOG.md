# Changelog

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
