# Agent roles

Every agent is a cold start. Read files and grep with your tools. Do not answer from memory. Read `copy-bar.md` (path in the prompt) before judging any string. Obey it. Do not invent a different style guide.

The prompt tells you `SOURCE` (the source locale, usually `en`) and `LOCALES` (every locale the project ships, source first). Findings carry a `text` (source-locale replacement) and a `translations` object with one entry per non-source locale in `LOCALES`. When `LOCALES` is only the source, `translations` is `{}`.

Return only the JSON the prompt's schema asks for. Empty lists are valid only after the tools ran.

---

## Finder

Scan every file under the given paths for **user-facing** copy. Match the shard dest:

- `code` / `web` — button labels, titles, subtitles, placeholders, tooltips, alerts, confirmations, empty states, menu items, status badges, toasts, CLI `--help` and error output, `String(localized:)`, SwiftUI `Text` / `Button` / `Label` / `navigationTitle` / `alert` / `confirmationDialog`, Android `getString` values, `t("…")` / `i18n.t` default values, JSX / template text, `NSLocalizedString`, `gettext` / `_()` sources
- `api` — user-visible `Abort(..., reason:)` / `reason:` / flash / error-body / validation messages the client shows
- `doc` — README, help, and guide copy the product audience reads
- `catalog` — localization values, not keys

Skip logs, comments, identifiers, URLs, analytics, DTO field names, i18n keys, agent skill files, tests (except pinned user-visible strings), and docs whose dest is not `doc`. Skip anything under the prompt's `EXCLUDE` list — another shard owns it.

For each issue, keep the worst failures. Cap 20 per shard, worst first. Skip copy that already passes the bar.

Each finding must have:

- `file` — absolute path
- `line` — integer
- `current` — the exact string now
- `reason` — why it fails the bar (one short sentence)
- `text` — replacement in the source locale
- `translations` — `{ "<locale>": "<replacement>" }` for every other locale in `LOCALES`
- `kind` — one of `title`, `button`, `body`, `error`, `empty`, `placeholder`, `badge`, `other`

`text` / `translations` must keep interpolation tokens. Do not report a finding you have not opened.

---

## Verifier

Independently inspect each finding. Open the file. Read the surrounding UI. Keep it only when all of these hold:

1. The string is actually shown to a user of the product.
2. The current wording fails the copy bar.
3. The proposed `text` / `translations` keep the same meaning and the same tokens.

Quote a line from the file as evidence before keeping it. Drop the rest when evidence is missing. Do not rubber-stamp the finder.

Return `confirmed` as the findings that survived (same shape as finder findings).

---

## Fixer

Apply only the confirmed findings. Read each file before editing.

- Change user-facing string literals / catalog values only. Do not restructure code.
- Keep interpolation tokens.
- Do not edit localization catalogs unless the shard dest is `catalog`; the localizer runs after every fixer and owns them. If you change or add a source-locale key (`String(localized:)`, `t("key")` default, `NSLocalizedString`, `getString` default, gettext source), list that key in `new_keys` so localization can follow.
- Do not touch files outside this shard or under its `EXCLUDE` list.
- Do not "clean up" nearby copy that was not confirmed.
- If a test asserts the old user-visible string, update that assertion in the same change.

Return `changed_files` (absolute paths you actually edited), `applied` (count), `skipped` (count), `new_keys` (array of strings), `notes` (short).

---

## Reviewer

Read the files that were just edited (or `git diff` those paths). Hunt for:

- Copy that still fails the bar
- Broken or reordered interpolation tokens
- Meaning changes, invented features, inconsistent terms
- Source changed but a locale missing / mismatched (or the reverse)
- User-facing errors that still leak internals

Return `clean=true` only when nothing remains. Otherwise `remaining` uses the same finding shape as the finder, with new `text` / `translations` for the leftover issues. Do not restyle copy that now passes.

---

## Localizer

Operate on the given catalogs. Formats you may meet: `.xcstrings`, `<lang>.lproj/*.strings` + `.stringsdict`, Android `res/values[-<lang>]/strings.xml`, `locales/<lang>.json|.yml` (flat or nested, i18next / vue-i18n / Rails), Flutter `.arb`, `.resx`, Java `.properties`, gettext `.po`, `.xliff`, Fluent `.ftl`.

- Run the gaps script from the prompt first. Fill every gap it lists. Re-run it at the end; the goal is zero gaps and zero errors.
- Every key the app uses must have a value in every locale the report marks `locales_required` for that catalog (by default the locales that catalog already ships; with `--strict`, all of `LOCALES`). For `.xcstrings`, each unit is `state: translated`, non-empty.
- Delete a catalog entry whose key is the empty string `""`.
- New source-locale keys from this run (`new_keys` plus any lookup call you find missing) must be added with every locale.
- Every translation must match the source meaning and the copy bar. Do not leave `needs_review` / empty / fuzzy values.
- Preserve interpolation and plural syntax. Use positional arguments only when a locale needs to reorder them.
- Keep the file's existing formatting (indentation, key order, trailing newline). Edit values; do not re-serialize the whole file with a different style. Do not rewrite keys you are not filling.
- A locale file that does not exist yet (for example `zh-Hans.json` next to `en.json`) is created with the same shape as the source file.

Return `changed_files`, `filled` (count of keys completed), `notes`.

---

## Shipper

Per git root that has changes from this run:

1. Intersect `changed_files` with `git status --porcelain`. Those paths only.
2. Run the cheap checks the prompt lists for that root (`CHECKS`). If the prompt lists none, run the first that applies: `make check` when a Makefile defines it, `swift build` for `Package.swift`, the `typecheck` / `lint` script from `package.json`, `cargo check`, `go build ./...`, `python3 -m compileall -q`, `dart analyze`. Never run the full test suite or an Xcode / Gradle build. Always run the gaps script over the catalogs and treat any `errors` as a failure. If a check fails on a copy-only change, fix the copy / test / catalog and re-run once. If it fails for an unrelated reason, stop and report — do not repair foreign breakage.
3. Commit with explicit pathspec only: `git commit -m "…" -- <paths>`. Never `git add -A`, `git add .`, `git add -u`, or `git commit -a`. If the tree has other dirty files, leave them exactly where they are.
4. Split into batches when a pre-commit hook refuses a wide commit. Do not set override environment variables to bypass hooks.
5. Message: imperative, about the user-visible copy (not "polish strings"). Append any trailer lines the prompt supplies.
6. If `push` is true, `git push -u origin HEAD` on the current branch. Never force-push. If push fails, report and leave the commit local.

Return `commits` (array of `{root, sha, files, pushed}`), `notes`. If nothing to commit, return empty `commits` and say so.
