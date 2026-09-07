# UI Copy Polish

A skill that rewrites **user-facing copy** so it is written, short, and immediately understandable — then commits and pushes. It works on any codebase: an Xcode app, an npm / Node project, a Cargo or Go tool, a Django or Rails site, an Android or Flutter app, a .NET solution, a docs folder, or a monorepo mixing them.

Pipeline:

**discover shards → find → verify → fix → review → fix (loop) → localize (plan → translate → merge) → commit → push**

It does not restyle developer logs, comments, identifiers, i18n keys, tests, or agent skill files. Every locale the project ships has to be complete when it finishes.

## Install

```bash
# Claude Code
git clone https://github.com/Lakr233/ui-copy-polish.git ~/.claude/skills/ui-copy-polish
# Grok
git clone https://github.com/Lakr233/ui-copy-polish.git ~/.grok/skills/ui-copy-polish
# Cursor
git clone https://github.com/Lakr233/ui-copy-polish.git ~/.cursor/skills/ui-copy-polish
```

Then run `/ui-copy-polish`. Hosts that match on description also pick it up for 过一遍文案, polish UI copy, 书面化.

## Usage

```
/ui-copy-polish
/ui-copy-polish code
/ui-copy-polish doc
/ui-copy-polish all
/ui-copy-polish web api --no-push
/ui-copy-polish ./apps/ios
/ui-copy-polish all --locales en,zh-Hans,ja
```

Dest classifiers split *what* is scanned. Remaining tokens are filesystem roots. A directory named like a dest token must be passed as a path (`./code`).

| Dest | Scope |
| --- | --- |
| `code` (`ui`) | Application source UI copy. **Default.** |
| `web` (`admin`) | HTML / JS / TS / template web UI |
| `api` (`backend`, `server`) | Server-side user-visible strings (controllers, routes, handlers, resolvers) |
| `doc` (`docs`) | User-facing documentation |
| `catalog` (`i18n`, `l10n`, `strings`) | Localization catalogs |
| `all` | All of the above |

| Flag | Effect |
| --- | --- |
| _(none)_ | Dest `code` from the current workspace, polish, commit, push |
| `path` | Limit discovery to that root |
| `--locales a,b` | Require these locales in every catalog (default: each catalog completes the locales it already ships) |
| `--max-shards N` | Cap the number of parallel shards (default 12) |
| `--no-commit` | Stop after edits |
| `--no-push` | Commit locally, do not push |

Commits use explicit pathspecs. Other dirty files in the tree are left alone.

## What it detects

`scripts/discover-copy-shards.py` walks the roots and emits shards, catalogs, locales, git roots, and a cheap check per repo:

| Stack | Recognised by | Check the shipper runs |
| --- | --- | --- |
| Make | `Makefile` with a `check` / `lint` target | `make check` |
| Xcode / SwiftPM | `*.xcodeproj`, `Package.swift` | `swift build` (no `xcodebuild`) |
| Node | `package.json` (+ pnpm / yarn / bun lockfile) | `<pm> run typecheck` / `lint` / `check`, else `tsc --noEmit` |
| Rust | `Cargo.toml` | `cargo check` |
| Go | `go.mod` | `go build ./...` |
| Python | `pyproject.toml`, `setup.py`, `requirements.txt` | `python3 -m compileall` |
| Ruby | `Gemfile` | `ruby -c` over `*.rb` |
| Flutter / Dart | `pubspec.yaml` | `flutter analyze` / `dart analyze` |
| Android / Gradle | `gradlew`, `build.gradle*` | catalog report only (a compile is too slow) |
| .NET | `*.sln`, `*.csproj` | `dotnet build` |
| PHP | `composer.json` | `php -l` |
| Elixir | `mix.exs` | `mix compile` |

Catalog formats the mergers complete (and `scripts/catalog-gaps.py` audits). Localization fans out: the gaps script emits one job per locale in chunks of at most 100 keys (`--emit-jobs --chunk-size 100`), a translator subagent handles each job, then one merger writes each catalog (every locale into one `.xcstrings` file).

| Format | Layout |
| --- | --- |
| Apple String Catalog | `*.xcstrings` |
| Apple legacy | `<lang>.lproj/*.strings`, `*.stringsdict` |
| Android | `res/values[-<lang>]/strings.xml`, `plurals.xml`, `arrays.xml` |
| i18next / vue-i18n / Rails | `locales/<lang>.json\|yml`, `locales/<lang>/<ns>.json` |
| Flutter | `intl_<lang>.arb`, `@@locale` |
| .NET | `<base>.<lang>.resx` |
| Java | `<base>_<lang>.properties` |
| gettext | `<lang>/LC_MESSAGES/*.po`, `<lang>.po` |
| XLIFF | `*.xliff`, `*.xlf` |
| Fluent | `<lang>/*.ftl` |

Locales come from those catalogs (`sourceLanguage`, `.lproj` names, `values-xx`, file stems, `@@locale`, `target-language`). Each catalog is completed for the locales it already ships — an Android module with `en` + `ja` next to a web app with `en` + `zh-Hans` keeps both sets as they are. Pass `--locales` to demand one set everywhere. A project without catalogs is edited in its source language only. YAML catalogs use PyYAML when installed and a built-in subset parser otherwise.

## What “good copy” means

See [`references/copy-bar.md`](references/copy-bar.md). In short:

- UI language, not chat and not a stack trace
- A user who has never seen the codebase understands what happened and what to do
- Titles 1–5 words, buttons 1–3 words
- Errors: what failed + the next step. No database names, file formats, JSON keys, HTTP status
- English Title Case on buttons and titles; `zh-Hans` 书面 UI 用语; every other locale in its own written UI register
- Docs (when dest includes `doc` / `all`) may be longer than UI chrome, still written and clear

## Structure

```
ui-copy-polish/
├── SKILL.md                         # Orchestrator (host-agnostic)
├── references/
│   ├── copy-bar.md                  # Writing standard
│   └── roles.md                     # Finder / verifier / fixer / reviewer / planner / translator / merger / shipper
├── scripts/
│   ├── discover-copy-shards.py      # Stack, dest, locale, and check discovery
│   ├── catalog-gaps.py              # Incomplete keys across every catalog format
│   ├── xcstrings-gaps.py            # Compatibility shim → catalog-gaps.py
│   └── test_copy_scripts.py         # python3 scripts/test_copy_scripts.py
└── workflows/
    ├── ui-copy-polish.rhai          # Engine for Grok
    └── ui-copy-polish.js            # Engine for Claude Code's Workflow tool
```

On Grok, the orchestrator copies `workflows/ui-copy-polish.rhai` to `~/.grok/workflows/` and launches it by name (`agent_budget: 256`). On Claude Code it launches `workflows/ui-copy-polish.js` through the `Workflow` tool. Anywhere else it reproduces the same phases with plain subagents.

## License

MIT
