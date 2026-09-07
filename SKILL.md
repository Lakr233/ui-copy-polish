---
name: ui-copy-polish
description: Polish user-facing UI copy in any codebase (Xcode, npm/Node, Rust, Go, Python, Android, Flutter, .NET, docs) with a workflow of subagents — find → verify → fix → review → fix (loop) → localize → commit → push. Use when the user runs /ui-copy-polish, or asks to 过一遍文案, polish UI copy, rewrite user-facing strings, 书面化, make copy UI-facing, or fix informal / developer-facing labels, errors, empty states, and alerts.
---

# UI copy polish

You are the orchestrator. Do not rewrite copy yourself. Discover shards, launch the engine once, report.

`SKILL_DIR` is the directory that contains this `SKILL.md`.

| File | Path |
| --- | --- |
| Copy bar | `SKILL_DIR/references/copy-bar.md` |
| Roles | `SKILL_DIR/references/roles.md` |
| Discover | `SKILL_DIR/scripts/discover-copy-shards.py` |
| Catalog gaps | `SKILL_DIR/scripts/catalog-gaps.py` |
| Engine (Grok) | `SKILL_DIR/workflows/ui-copy-polish.rhai` |
| Engine (Claude Code) | `SKILL_DIR/workflows/ui-copy-polish.js` |

Read the copy bar once so you can brief the user. Do not restyle strings in the parent session.

## Arguments

Parse `$ARGUMENTS`:

- `--no-commit` → `commit: false`
- `--no-push` → `push: false`
- `--locales a,b` → passed to discover (overrides catalog detection and sets `strict_locales`, so every catalog must carry every listed locale)
- `--max-shards N` → passed to discover
- Every other token is passed through to `discover-copy-shards.py` (dest classifiers and/or paths). Dest aliases live in that script's docstring: `code` `web` `api` `doc` `catalog` `all`.
- Empty → discover from the current working directory, dest `code`.

Defaults: `commit: true`, `push: true`.

## Step 1 — Discover

```bash
python3 "<SKILL_DIR>/scripts/discover-copy-shards.py" --cwd "<PWD>" <roots-and-dests...>
```

The script prints JSON: `workspace`, `dests`, `roots`, `shards` (each with `paths` and `exclude`), `catalogs`, `git_roots`, `locales`, `source_locale`, `strict_locales`, `checks`.

It works on any layout — a single Xcode app, an npm package, a Cargo workspace, a Go module, a Django site, an Android or Flutter app, a monorepo of several — because it classifies by suffix and well-known directory names, reads locales out of whatever catalogs exist (`.xcstrings`, `.lproj`, `values-*/strings.xml`, `locales/*.json|yml`, `.arb`, `.po`, `.resx`, `.properties`, `.xliff`, `.ftl`), and picks a cheap check per git root (`make check`, `swift build`, the `typecheck`/`lint` npm script, `cargo check`, `go build`, …).

If `shards` is empty, stop and say nothing user-facing was found. Do not launch agents.

Tell the user in one line: how many shards, which locales were detected (`locales` — if the project ships none, only the source locale is edited), and which checks will run. If the detected locales look wrong, they can re-run with `--locales`.

Stay in the git repos the script named.

## Step 2 — Launch the engine once

Build `args` = the discover JSON plus:

```json
{
  "copy_bar_path": "<SKILL_DIR>/references/copy-bar.md",
  "roles_path": "<SKILL_DIR>/references/roles.md",
  "gaps_script": "<SKILL_DIR>/scripts/catalog-gaps.py",
  "commit": true,
  "push": true,
  "commit_trailers": "<any trailer lines your host requires, else omit>"
}
```

Override `commit` / `push` from the flags. Then pick the engine for the host you are running in:

**Grok** — copy the rhai script into the trusted workflow home and launch by name (`agent_budget: 256`):

```bash
mkdir -p "$HOME/.grok/workflows"
cp "<SKILL_DIR>/workflows/ui-copy-polish.rhai" "$HOME/.grok/workflows/ui-copy-polish.rhai"
```

Launch with `name: "ui-copy-polish"` and the `args` above. Do not pass a Desktop `script_path` — that path is not trusted.

**Claude Code** — call the `Workflow` tool once with `scriptPath: "<SKILL_DIR>/workflows/ui-copy-polish.js"` and the `args` above. The user invoking this skill is the opt-in the tool requires. Set `read_only_agent_type` in `args` if your session's read-only agent is not called `Explore`.

**Any other host** — use the fallback below.

After launching, stop spawning your own finders/fixers. Do not poll. Tell the user the workflow display name and that Ship commits with explicit pathspec, then pushes the current branch. Never force-push. Never `git add -A`.

The engine is:

**find → verify → fix → review → fix (loop, max 3) → localize (plan → translate → merge) → commit → push**

Each shard runs its own chain; fixers never edit outside their shard (or inside its `exclude` list). Translators never edit catalogs. Only mergers write catalogs.

## Fallback (only if no workflow engine is available or it errors)

Reproduce the same phases with subagents. Cold-start every child: it must read the copy bar and the matching section of `roles.md` before judging a string, and every prompt carries `SOURCE`, `LOCALES`, the shard's `paths`, and its `exclude` list.

1. **Find** — one read-only subagent per shard. Prompt = Finder section + shard dest + shard paths/exclude. Empty findings only after grep.
2. **Verify** — one read-only subagent per shard that returned findings. Keep only items with quoted evidence. Drop out-of-shard paths.
3. **Fix** — one read-write subagent per shard with confirmed items. No worktree isolation. Confirmed replacements only. Non-catalog shards do not edit catalogs.
4. **Review → fix loop** — one read-only reviewer per edited shard. If `remaining` is non-empty, fix those shards again. Stop after 3 rounds or when a round returns nothing new.
5. **Localize** — do not fill catalogs in one agent.
   1. Run `catalog-gaps.py --locales <locales> --source <source> [--strict] --emit-jobs --chunk-size 100` on every catalog. That writes one job file per locale chunk.
   2. One read-only translator per job (one locale, ≤100 keys). Each returns JSON `{ locale, items: [{ catalog, key, text }] }`. They do not edit catalogs.
   3. One read-write merger per catalog. Apply every translator item for that file (all locales merge into one `.xcstrings`), delete the empty `""` key, add `new_keys`, re-run the gaps script.
6. **Ship** — one agent with shell access. Intersect this run's files with `git status --porcelain`. Run the `checks` commands for each git root that changed (plus the gaps script). `git commit -m "…" -- <paths>`. Push `HEAD` if `push` is true.

Wait for each panel to finish before starting the next phase. Do not repair unrelated build breakage. Do not touch dirty files this run did not change.

## Hard rules

- User-visible copy only. The copy bar is the only style guide.
- Every locale a catalog ships, complete. Never add a locale a catalog does not ship unless the user passed `--locales`.
- Keep interpolation tokens.
- Pathspec commits. Leave other sessions' dirty files alone.
- One repo at a time at git time; the engine already splits by `git_roots`.
