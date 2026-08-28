# Copy bar

User-facing copy only. If a person using the product never sees the string, leave it.

This bar is the same for a SwiftUI sheet, a React modal, a CLI error, a Rails flash, an Android snackbar, or a README. The surface changes; the standard does not.

A string passes only when all of these are true:

1. **UI language.** Written interface copy, not chat, not a log, not a code comment, not a developer abort dump.
2. **Understandable.** Someone who has never seen the codebase knows what happened and what to do.
3. **Short.** Titles 1–5 words. Buttons 1–3 words. Body: one sentence when one sentence is enough.
4. **Clear.** One meaning. One action. No hedging, no slang, no "oops" / "whoops" / "hang tight".

Do not "improve" copy that already passes. Do not invent features. Do not change product meaning.

## Voice

- Second person. Direct. Do not blame the user.
- Errors: what happened + the next step. Never internals (database names, file formats like p12 or JSON keys, HTTP status codes, stack traces, "this is a bug", table names, env vars, exception class names).
- Empty states: what this surface is + the next action.
- In-progress: verb + ellipsis `…` (`Starting Simulator…`, `Uploading…`).
- Product names stay as themselves: the product's own name, plus platform and vendor names (App Store, TestFlight, Simulator, GitHub, Google, Apple, Docker, npm, Slack).
- Command-line tools: the same bar applies to `--help` text, error output, and prompts a person reads. Flags, subcommands, and file paths are identifiers — leave them.

## Source language (English)

- Buttons, tabs, navigation titles, alert titles, menu items: Title Case (`Create App`, `Developer Mode`, `Choose Team`).
- Sentences, errors, descriptions, empty states, placeholders, toasts: Sentence case.
- Prefer a specific verb: Save, Delete, Retry, Sign In, Choose Team, Create App.
- No slang, no memes, no `Dev Mode`, no leading `＋` on a button that already says Create.

## Simplified Chinese (`zh-Hans`)

Applies when `zh-Hans` (or `zh-CN`, `zh`) is one of the project's locales.

- 简体中文书面 UI 用语，不是口语聊天。
- 按钮短：创建、删除、重试、登录、选择团队。
- 与英文同一意思，不要写成更长的解释。
- 产品名与平台名保留原文：App Store、TestFlight、GitHub。其余用中文。
- 用中文标点。省略号用 `…`。

## Other locales

Every locale the project ships gets the same treatment: written UI register for that language, same meaning as the source, same length class, native punctuation, product and platform names untouched. Do not add a locale the project does not ship. Do not drop one it does.

## Docs

When the shard dest is `doc`, the reader is still a product user (README, help, guides). Prose may be longer than UI chrome. Headings stay Title Case in English. Lead with what the reader can do. Cut filler. Do not rewrite agent skill files, RFCs, contributor guides, or changelog machinery.

## Tokens and structure

- Keep interpolation tokens and their order (`\(name)`, `%@`, `%lld`, `{name}`, `{{count}}`, `%s`, `%1$s`, `${name}`, `<0>…</0>`). Switch to positional (`%1$@`) only when two locales need a reordered argument.
- Keep ICU / plural syntax intact (`{count, plural, one {…} other {…}}`, `stringsdict`, Android `<plurals>`).
- Do not rewrite identifiers, URLs, SF Symbol / icon names, analytics events, DTO field names, i18n *keys* (only their values), or log lines (`os.log`, `Logger`, `print`, `console.log`, `assert`, `tracing::`, `log.Printf`).
- Same concept, same word, every locale. If the UI says conversation, do not also say chat for the same object.

## Examples (real rewrites)

| Fail | Pass |
| --- | --- |
| Dev Mode | Developer Mode |
| Choose a team | Choose Team |
| ＋ Create new app | Create App |
| Couldn't Load Document | Unable to Load Document |
| Starting the simulator… | Starting Simulator… |
| This chat is gone from the loaded data. This state is a bug… | This conversation could not be loaded. Select another conversation or restart the app. |
| PostgreSQL is required… / p12 must be base64 / model cannot be null; send `{"model":"default"}` | A short user-facing error: what failed, what to do. |
| `Error: ENOENT: no such file or directory, open 'config.json'` (shown in the UI) | Configuration file not found. Check the path and try again. |
| Oops! Something went wrong 😅 | Something went wrong. Try again. |

## Out of scope

Leave these alone unless they are rendered in a user-visible surface:

- Tests, fixtures, snapshots, Storybook stories (update an assertion only when a user-visible string it pins actually changed)
- Agent skill files, system prompts, comments
- Build artifacts, generated code, vendor, `node_modules`, lockfiles
- OpenAPI / machine contracts, schema descriptions, protobuf
- Documentation, unless the shard dest is `doc`
