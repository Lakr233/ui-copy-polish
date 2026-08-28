#!/usr/bin/env python3
"""Discover user-facing copy shards for ui-copy-polish. Prints JSON on stdout.

Works on any project layout: Xcode / SwiftPM, npm / pnpm / yarn / bun, Cargo,
Go, Python, Ruby, Flutter, Gradle, .NET, PHP, plain Makefile trees, and
monorepos that mix them. Nothing here is project specific; the walk is driven
by file suffixes, well-known directory names, and the catalogs it finds.

Positional tokens are dest classifiers and/or filesystem roots. Dest aliases:

  code (ui)             application source UI copy          [default]
  web (admin)           HTML / JS / TS / template web UI
  api (backend, server) server-side user-visible strings
  doc (docs)            user-facing documentation
  catalog (catalogs, i18n, l10n, strings)
                        localization catalogs
  all                   code + web + api + doc + catalog

A folder named like a dest token must be passed as a path (./code).

Output keys:

  workspace, dests, roots         what was asked
  shards[]                        {id, dest, root, paths[], exclude[]} — exclude
                                  lists subpaths another shard owns, so two
                                  fixers never edit the same file
  catalogs[]                      every localization catalog under the roots
  locales[], source_locale        detected from the catalogs (override with
                                  --locales / --source-locale)
  strict_locales                  true when --locales was given: every catalog
                                  must then carry every locale; otherwise each
                                  catalog completes only the locales it ships
  git_roots[]                     repos to commit in
  checks[]                        {root, stack[], commands[], notes[]} — the
                                  cheap verification the shipper runs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEST_ALIASES = {
    "code": "code",
    "ui": "code",
    "web": "web",
    "admin": "web",
    "api": "api",
    "backend": "api",
    "server": "api",
    "doc": "doc",
    "docs": "doc",
    "catalog": "catalog",
    "catalogs": "catalog",
    "i18n": "catalog",
    "l10n": "catalog",
    "strings": "catalog",
    "all": "all",
}
ALL_DESTS = ("code", "web", "api", "doc", "catalog")
DEFAULT_DESTS = ("code",)

SKIP_DIR_NAMES = {
    ".git",
    ".build",
    ".swiftpm",
    "DerivedData",
    "node_modules",
    "bower_components",
    "target",
    "Pods",
    "Carthage",
    "xcuserdata",
    "__pycache__",
    "site-packages",
    "dist",
    "coverage",
    "vendor",
    "Vendors",
    "vendors",
    "third_party",
    "ThirdParty",
    "venv",
    "env",
    "build",
    "builds",
    "out",
    "bin",
    "obj",
    "Migrations",
    "migrations",
    "Generated",
    "generated",
    "gen",
    "proto",
    "protos",
    "storybook-static",
    "__snapshots__",
    "snapshots",
    "skills",
    "tmp",
    "temp",
    "logs",
    "log",
}
SKIP_DIR_SUFFIXES = (
    ".bundle",
    ".xcodeproj",
    ".xcworkspace",
    ".xcassets",
    ".egg-info",
    ".framework",
    ".xcframework",
    ".app",
)
TEST_DIR_NAMES = {
    "Tests",
    "tests",
    "__tests__",
    "test",
    "spec",
    "specs",
    "e2e",
    "fixtures",
    "Fixtures",
    "Mocks",
    "mocks",
    "__mocks__",
    "testdata",
    "UITests",
    "androidTest",
}
DOC_DIR_NAMES = {
    "docs",
    "doc",
    "documentation",
    "Documentation",
    "Documents",
    "help",
    "guides",
    "guide",
    "manual",
    "wiki",
    "handbook",
}
SKIP_DOC_NAMES = {
    "AGENTS.md",
    "SKILL.md",
    "CLAUDE.md",
    "GEMINI.md",
    "CODEOWNERS",
    "LICENSE",
    "LICENSE.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "PULL_REQUEST_TEMPLATE.md",
}
SKIP_DOC_PREFIXES = ("CHANGELOG", "CHANGES", "HISTORY", "RELEASE", "TODO")
API_DIR_NAMES = {
    "Controllers",
    "controllers",
    "controller",
    "routes",
    "router",
    "routers",
    "api",
    "apis",
    "server",
    "backend",
    "handlers",
    "handler",
    "resolvers",
    "graphql",
    "endpoints",
    "Endpoints",
    "rpc",
    "grpc",
    "middleware",
    "middlewares",
}
WEB_SUFFIXES = {
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".mts",
    ".cts",
    ".vue",
    ".svelte",
    ".astro",
    ".html",
    ".htm",
    ".ejs",
    ".hbs",
    ".handlebars",
    ".mustache",
    ".njk",
    ".pug",
    ".jinja",
    ".jinja2",
    ".j2",
    ".twig",
    ".erb",
    ".haml",
    ".slim",
    ".cshtml",
    ".razor",
    ".heex",
    ".leex",
    ".elm",
    ".res",
}
CODE_SUFFIXES = WEB_SUFFIXES | {
    ".swift",
    ".m",
    ".mm",
    ".storyboard",
    ".xib",
    ".kt",
    ".kts",
    ".java",
    ".scala",
    ".dart",
    ".cs",
    ".fs",
    ".vb",
    ".xaml",
    ".qml",
    ".py",
    ".rb",
    ".go",
    ".rs",
    ".php",
    ".ex",
    ".exs",
    ".lua",
    ".gd",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".zig",
    ".nim",
    ".clj",
    ".cljs",
    ".sh",
}
DOC_SUFFIXES = {".md", ".mdx", ".rst", ".adoc", ".txt"}
CATALOG_SUFFIXES = {
    ".xcstrings",
    ".strings",
    ".stringsdict",
    ".po",
    ".pot",
    ".arb",
    ".xliff",
    ".xlf",
    ".resx",
    ".ftl",
}
LOCALE_DIR_FILE_SUFFIXES = {".json", ".json5", ".yml", ".yaml", ".toml", ".properties"}
LOCALE_DIR_NAMES = {
    "locales",
    "locale",
    "i18n",
    "l10n",
    "lang",
    "langs",
    "languages",
    "translations",
    "translation",
    "messages",
    "Strings",
    "strings",
    "intl",
}
ANDROID_RES_NAMES = {"strings.xml", "plurals.xml", "arrays.xml"}
SKIP_FILE_PATTERNS = (
    re.compile(r"\.min\.(js|css)$"),
    re.compile(r"\.d\.ts$"),
    re.compile(r"\.(map|lock|snap)$"),
    re.compile(r"\.(generated|gen|g|freezed|pb|pbobjc)\.\w+$"),
    re.compile(r"_pb2(_grpc)?\.py$"),
    re.compile(r"\.designer\.cs$", re.IGNORECASE),
    re.compile(r"\.(stories|story)\.\w+$"),
    re.compile(r"\.(test|spec)\.\w+$"),
    re.compile(r"_test\.(go|py|rs|rb|dart)$"),
    re.compile(r"^test_.*\.py$"),
    re.compile(r"Tests?\.swift$"),
    re.compile(r"Tests?\.(kt|java|cs)$"),
    re.compile(r"^(package|package-lock|tsconfig|composer)\.json$"),
)
CODE_ANCHORS = (
    "interface",
    "sources",
    "source",
    "src",
    "lib",
    "app",
    "apps",
    "packages",
    "crates",
    "cmd",
    "internal",
    "pkg",
    "modules",
    "features",
    "frontend",
    "backend",
    "web",
    "ios",
    "android",
    "macos",
    "desktop",
    "mobile",
    "client",
    "server",
    "components",
    "views",
    "screens",
    "pages",
)
UI_ANCHORS = {"interface", "views", "screens", "components", "pages"}
MAX_SHARDS = 12

# ISO 639-1 plus the handful of three-letter codes projects actually ship.
LANGUAGE_CODES = set(
    """
    aa ab af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co
    cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd
    gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv
    ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg
    mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os
    pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss
    st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo
    wa wo xh yi yo za zh zu
    fil haw ceb yue wuu hak nan ast tlh
    """.split()
)
LOCALE_RE = re.compile(r"^([A-Za-z]{2,3})(?:[-_]([A-Za-z]{2,4}|\d{3}))?(?:[-_]([A-Za-z]{2}|\d{3}))?$")


def is_git_root(path: Path) -> bool:
    return (path / ".git").exists()


def child_git_repos(path: Path) -> list[Path]:
    repos: list[Path] = []
    try:
        entries = sorted(path.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return repos
    for child in entries:
        if child.is_dir() and is_git_root(child):
            repos.append(child)
    return repos


def add_dest(dests: set[str], token: str) -> bool:
    name = DEST_ALIASES.get(token)
    if name is None:
        return False
    if name == "all":
        dests.update(ALL_DESTS)
    else:
        dests.add(name)
    return True


def parse_tokens(tokens: list[str], cwd: Path) -> tuple[set[str], list[Path]]:
    dests: set[str] = set()
    roots: list[Path] = []
    for item in tokens:
        if add_dest(dests, item):
            continue
        raw = Path(item).expanduser()
        path = raw if raw.is_absolute() else (cwd / raw)
        path = path.resolve()
        if not path.exists():
            print(f"discover-copy-shards: path not found: {path}", file=sys.stderr)
            continue
        if path.is_file():
            path = path.parent
        roots.append(path)
    return dests, roots


def resolve_roots(cwd: Path, requested: list[Path]) -> list[Path]:
    if requested:
        return requested
    if is_git_root(cwd):
        return [cwd]
    children = child_git_repos(cwd)
    return children or [cwd]


# --- locales -----------------------------------------------------------------


def looks_like_locale(token: str) -> bool:
    match = LOCALE_RE.match(token)
    if not match:
        return False
    return match.group(1).lower() in LANGUAGE_CODES


def locale_from_lproj(name: str) -> str | None:
    if not name.endswith(".lproj"):
        return None
    code = name[: -len(".lproj")]
    if code == "Base" or not looks_like_locale(code):
        return None
    return code


def locale_from_android_values(name: str) -> str | None:
    # values-zh-rCN → zh-CN, values-b+sr+Latn → sr-Latn, values-fr → fr
    if not name.startswith("values-"):
        return None
    rest = name[len("values-") :]
    if rest.startswith("b+"):
        code = rest[2:].replace("+", "-")
    else:
        parts = rest.split("-")
        if not parts or not looks_like_locale(parts[0]):
            return None
        code = parts[0]
        if len(parts) > 1 and parts[1].startswith("r") and len(parts[1]) == 3:
            code += "-" + parts[1][1:]
    return code if looks_like_locale(code) else None


def locale_from_suffixed_name(stem: str) -> str | None:
    # messages_zh_CN.properties, Resources.zh-Hans.resx, intl_en.arb, app_de.arb
    for sep in (".", "_"):
        if sep in stem:
            head, tail = stem.rsplit(sep, 1)
            if looks_like_locale(tail):
                return tail
            if sep == "_" and "_" in head:
                # messages_zh_CN → zh_CN
                head2, mid = head.rsplit("_", 1)
                candidate = f"{mid}_{tail}"
                if looks_like_locale(candidate):
                    return candidate
    return None


def locales_from_xcstrings(path: Path) -> tuple[set[str], str | None]:
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), None
    found: set[str] = set()
    source = catalog.get("sourceLanguage")
    if isinstance(source, str) and source:
        found.add(source)
    for entry in (catalog.get("strings") or {}).values():
        for code in ((entry or {}).get("localizations") or {}).keys():
            found.add(code)
    return found, source if isinstance(source, str) else None


def locales_from_arb(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    code = data.get("@@locale") if isinstance(data, dict) else None
    if isinstance(code, str) and looks_like_locale(code):
        return code
    return locale_from_suffixed_name(path.stem)


def locales_from_xliff(path: Path) -> set[str]:
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:4000]
    except OSError:
        return set()
    return {
        code
        for code in re.findall(r'(?:target-language|trgLang)="([^"]+)"', head)
        if looks_like_locale(code)
    }


def locale_of_catalog(path: Path) -> tuple[set[str], str | None]:
    """Return (locales, source_locale_hint) for one catalog file."""
    suffix = path.suffix
    parts = path.parts
    if suffix == ".xcstrings":
        return locales_from_xcstrings(path)
    if suffix in {".strings", ".stringsdict"}:
        for part in parts:
            code = locale_from_lproj(part)
            if code:
                return {code}, None
        return set(), None
    if suffix == ".arb":
        code = locales_from_arb(path)
        return ({code} if code else set()), None
    if suffix in {".xliff", ".xlf"}:
        return locales_from_xliff(path), None
    if suffix in {".po", ".pot"}:
        for part in reversed(parts[:-1]):
            if looks_like_locale(part):
                return {part}, None
        if suffix == ".po" and looks_like_locale(path.stem):
            return {path.stem}, None
        return set(), None
    if suffix in {".resx", ".properties"}:
        code = locale_from_suffixed_name(path.stem)
        return ({code} if code else set()), None
    if path.name in ANDROID_RES_NAMES:
        parent = path.parent.name
        code = locale_from_android_values(parent)
        return ({code} if code else set()), None
    if suffix in LOCALE_DIR_FILE_SUFFIXES:
        # locales/en.json, locales/en/common.json, i18n/zh-Hans/strings.yml
        if looks_like_locale(path.stem):
            return {path.stem}, None
        for part in reversed(parts[:-1]):
            if part in LOCALE_DIR_NAMES:
                break
            if looks_like_locale(part):
                return {part}, None
        return set(), None
    return set(), None


def detect_locales(catalogs: list[Path]) -> tuple[list[str], str | None]:
    found: dict[str, int] = {}
    source: str | None = None
    for path in catalogs:
        codes, hint = locale_of_catalog(path)
        for code in codes:
            found[code] = found.get(code, 0) + 1
        if hint and not source:
            source = hint
    ordered = sorted(found, key=lambda code: (-found[code], code))
    if not source:
        for candidate in ("en", "en-US", "en_US", "Base"):
            if candidate in found:
                source = candidate
                break
    if not source and ordered:
        source = ordered[0]
    if source and source in ordered:
        ordered.remove(source)
        ordered.insert(0, source)
    return ordered, source


# --- classification ----------------------------------------------------------


def should_skip_dir(name: str, dests: set[str]) -> bool:
    if name.startswith("."):
        return True
    if name.endswith(SKIP_DIR_SUFFIXES):
        return True
    if name in SKIP_DIR_NAMES or name in TEST_DIR_NAMES:
        return True
    if name in DOC_DIR_NAMES and "doc" not in dests:
        return True
    return False


def should_skip_file(name: str) -> bool:
    return any(pattern.search(name) for pattern in SKIP_FILE_PATTERNS)


def in_locale_dir(path: Path) -> bool:
    return any(part in LOCALE_DIR_NAMES or part.endswith(".lproj") for part in path.parts[:-1])


def is_catalog(path: Path) -> bool:
    suffix = path.suffix
    if suffix in CATALOG_SUFFIXES:
        return True
    if path.name in ANDROID_RES_NAMES:
        parent = path.parent.name
        return parent == "values" or parent.startswith("values-")
    if suffix in LOCALE_DIR_FILE_SUFFIXES:
        return in_locale_dir(path)
    return False


def is_doc(path: Path, root: Path) -> bool:
    if path.suffix not in DOC_SUFFIXES:
        return False
    if path.name in SKIP_DOC_NAMES:
        return False
    if path.name.upper().startswith(SKIP_DOC_PREFIXES):
        return False
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    parts = rel.parts
    if any(part in DOC_DIR_NAMES for part in parts):
        return path.suffix != ".txt"
    if len(parts) == 1 and path.name.upper().startswith("README"):
        return True
    return False


def is_api_path(root: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return False
    return any(part in API_DIR_NAMES for part in parts[:-1])


def classify(root: Path, path: Path, dests: set[str]) -> str | None:
    suffix = path.suffix
    if is_catalog(path):
        return "catalog" if "catalog" in dests else None
    if is_doc(path, root):
        return "doc" if "doc" in dests else None
    if suffix not in CODE_SUFFIXES:
        return None
    if should_skip_file(path.name):
        return None
    api = is_api_path(root, path)
    web = suffix in WEB_SUFFIXES
    if api and "api" in dests:
        return "api"
    if web and "web" in dests:
        return "web"
    if "code" in dests:
        return "code"
    return None


def skip_rel(root: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part in TEST_DIR_NAMES or part in SKIP_DIR_NAMES for part in parts[:-1])


def iter_files(root: Path, dests: set[str]) -> tuple[list[tuple[Path, str]], list[Path]]:
    tagged: list[tuple[Path, str]] = []
    catalogs: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not should_skip_dir(name, dests)]
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            if skip_rel(root, path):
                continue
            if is_catalog(path):
                catalogs.append(path)
            dest = classify(root, path, dests)
            if dest:
                tagged.append((path, dest))
    return tagged, catalogs


# --- sharding ----------------------------------------------------------------


def shard_dir(root: Path, file: Path, dest: str) -> tuple[str, Path]:
    rel = file.relative_to(root)
    parts = list(rel.parts[:-1])

    if dest == "catalog":
        return f"catalog-{file.stem}", file

    if dest == "doc":
        if parts and parts[0] in DOC_DIR_NAMES:
            if len(parts) > 1:
                return f"doc-{parts[1]}", root / parts[0] / parts[1]
            return "doc", root / parts[0]
        return f"doc-{file.stem}", file

    if dest == "api":
        # Shard at the API directory itself so it never equals its web/code parent.
        for idx, part in enumerate(parts):
            if part in API_DIR_NAMES:
                owner = parts[idx - 1] if idx > 0 else part
                return f"api-{owner}", root.joinpath(*parts[: idx + 1])

    # Shallowest anchor wins (apps/web/src/... shards per app), then descend while the
    # next segment is itself a UI anchor (App/Interface/Settings shards per screen group).
    for idx, part in enumerate(parts):
        if part.lower() not in CODE_ANCHORS:
            continue
        while idx + 1 < len(parts) and parts[idx + 1].lower() in UI_ANCHORS:
            idx += 1
        anchor = parts[idx].lower()
        prefix = f"{dest}-ui" if anchor in UI_ANCHORS else dest
        if idx + 1 < len(parts):
            return f"{prefix}-{parts[idx + 1]}", root.joinpath(*parts[: idx + 2])
        return f"{prefix}-{anchor}", root.joinpath(*parts[: idx + 1])
    if parts:
        return f"{dest}-{parts[0]}", root / parts[0]
    return dest, root


def slug(text: str) -> str:
    out = []
    prev_dash = False
    for char in text.lower():
        if char.isalnum():
            out.append(char)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-") or "shard"


def family_of(shard_id: str) -> str:
    return shard_id.split("-", 1)[0]


def merge_pair(items: list[tuple[str, list[str]]]) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    best_key: tuple[int, int, str] | None = None
    for i, (id_a, paths_a) in enumerate(items):
        for j, (id_b, paths_b) in enumerate(items):
            if j <= i:
                continue
            if family_of(id_a) != family_of(id_b):
                continue
            key = (len(paths_a) + len(paths_b), min(len(paths_a), len(paths_b)), id_a)
            if best_key is None or key < best_key:
                best_key = key
                best = (i, j)
    return best


def is_under(path: str, ancestor: str) -> bool:
    return path != ancestor and path.startswith(ancestor.rstrip("/") + "/")


def collapse_nested(paths: list[str]) -> list[str]:
    """Drop paths that sit under another path in the same list."""
    kept = []
    for path in sorted(set(paths)):
        if not any(is_under(path, other) for other in paths if other != path):
            kept.append(path)
    return kept


def group_shards(root: Path, files: list[tuple[Path, str]], max_shards: int) -> list[dict]:
    buckets: dict[str, set[Path]] = {}
    dest_of: dict[str, str] = {}
    for file, dest in files:
        key, directory = shard_dir(root, file, dest)
        shard_id = slug(key)
        buckets.setdefault(shard_id, set()).add(directory)
        dest_of[shard_id] = dest

    items: list[tuple[str, list[str]]] = [
        (key, sorted(path.as_posix() for path in dirs)) for key, dirs in buckets.items()
    ]
    items.sort(key=lambda kv: kv[0])
    while len(items) > max_shards:
        pair = merge_pair(items)
        if pair is None:
            break
        i, j = pair
        id_a, paths_a = items[i]
        id_b, paths_b = items[j]
        merged = (id_a, collapse_nested(paths_a + paths_b))
        items = [merged] + [item for k, item in enumerate(items) if k not in {i, j}]

    shards: list[dict] = []
    used_ids: set[str] = set()
    for raw_id, paths in sorted(items, key=lambda kv: kv[0]):
        shard_id = raw_id
        n = 2
        while shard_id in used_ids:
            shard_id = f"{raw_id}-{n}"
            n += 1
        used_ids.add(shard_id)
        shards.append(
            {
                "id": shard_id,
                "dest": dest_of[raw_id],
                "root": str(root),
                "paths": collapse_nested(paths),
                "exclude": [],
            }
        )
    return shards


DEST_PRIORITY = {"catalog": 0, "api": 1, "web": 2, "code": 3, "doc": 4}


def merge_equal_paths(shards: list[dict]) -> list[dict]:
    """Two shards that own the same directory become one; two fixers must never share a path."""
    merged: list[dict] = []
    for shard in sorted(shards, key=lambda s: (DEST_PRIORITY.get(s["dest"], 9), s["id"])):
        target = next(
            (m for m in merged if m["root"] == shard["root"] and set(m["paths"]) & set(shard["paths"])),
            None,
        )
        if target is None:
            merged.append(dict(shard))
            continue
        target["paths"] = collapse_nested(target["paths"] + shard["paths"])
    return sorted(merged, key=lambda s: s["id"])


def carve_overlaps(shards: list[dict]) -> list[dict]:
    """Give every shard an exclude list of subpaths that another shard owns."""
    for shard in shards:
        exclude: list[str] = []
        for other in shards:
            if other is shard:
                continue
            for other_path in other["paths"]:
                if any(is_under(other_path, own) for own in shard["paths"]):
                    exclude.append(other_path)
        shard["exclude"] = sorted(set(exclude))
    return shards


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def git_root_of(path: Path) -> Path | None:
    current = path if path.is_dir() else path.parent
    for candidate in [current, *current.parents]:
        if is_git_root(candidate):
            return candidate
    return None


# --- stack + checks ----------------------------------------------------------


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def makefile_targets(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    return {m.group(1) for m in re.finditer(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", text, re.MULTILINE)}


def node_runner(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm run"
    if (root / "yarn.lock").exists():
        return "yarn run"
    if (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        return "bun run"
    if (root / "deno.json").exists() or (root / "deno.jsonc").exists():
        return "deno task"
    return "npm run"


def detect_checks(root: Path) -> dict:
    stack: list[str] = []
    commands: list[str] = []
    notes: list[str] = []
    seen: set[str] = set()

    def add(command: str) -> None:
        if command not in seen:
            seen.add(command)
            commands.append(command)

    has = lambda name: (root / name).exists()  # noqa: E731
    glob = lambda pattern: any(root.glob(pattern))  # noqa: E731

    if has("Makefile") or has("makefile") or has("GNUmakefile"):
        stack.append("make")
        targets = set()
        for name in ("Makefile", "makefile", "GNUmakefile"):
            if has(name):
                targets |= makefile_targets(root / name)
        for target in ("check", "lint", "verify-copy"):
            if target in targets:
                add(f"make {target}")
                break

    if glob("*.xcodeproj") or glob("*.xcworkspace"):
        stack.append("xcode")
    if has("Package.swift"):
        stack.append("swiftpm")
        add("swift build")
    elif "xcode" in stack and not commands:
        notes.append("Xcode project without a Makefile check target: xcodebuild is too slow for a copy change; rely on the catalog gap report.")

    if has("package.json"):
        stack.append("node")
        scripts = read_json(root / "package.json").get("scripts") or {}
        runner = node_runner(root)
        picked = False
        for name in ("typecheck", "type-check", "lint", "check", "test:types"):
            if name in scripts:
                add(f"{runner} {name}")
                picked = True
                break
        if not picked:
            if (root / "tsconfig.json").exists():
                add("npx tsc --noEmit -p tsconfig.json")
            else:
                notes.append("package.json has no typecheck/lint/check script; nothing cheap to run.")

    if has("Cargo.toml"):
        stack.append("rust")
        add("cargo check --quiet")
    if has("go.mod"):
        stack.append("go")
        add("go build ./...")
    if has("pyproject.toml") or has("setup.py") or has("setup.cfg") or has("requirements.txt"):
        stack.append("python")
        add("python3 -m compileall -q -x '(\\.venv|venv|env|node_modules|build|dist)' .")
    if has("Gemfile"):
        stack.append("ruby")
        add("ruby -e 'Dir[\"**/*.rb\"].reject{|f| f =~ %r{/(vendor|node_modules|tmp)/}}.each{|f| system(\"ruby\",\"-c\",f,out: File::NULL) or abort(f)}'")
    if has("pubspec.yaml"):
        try:
            flutter = "flutter" in (root / "pubspec.yaml").read_text(encoding="utf-8", errors="ignore")
        except OSError:
            flutter = False
        stack.append("flutter" if flutter else "dart")
        add("flutter analyze --no-pub" if flutter else "dart analyze")
    if has("gradlew") or glob("build.gradle*") or glob("settings.gradle*"):
        stack.append("gradle")
        notes.append("Gradle project: a compile is slow; rely on the catalog gap report for strings.xml.")
    if glob("*.sln") or glob("*.csproj") or glob("*.fsproj"):
        stack.append("dotnet")
        add("dotnet build --nologo -v quiet")
    if has("composer.json"):
        stack.append("php")
        add("find . -name '*.php' -not -path '*/vendor/*' -print0 | xargs -0 -n1 php -l > /dev/null")
    if has("mix.exs"):
        stack.append("elixir")
        add("mix compile --warnings-as-errors")

    if not commands and not notes:
        notes.append("No build system recognised; the shipper only validates catalogs.")
    return {"root": str(root), "stack": stack, "commands": commands, "notes": notes}


# --- main --------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover UI copy shards. Tokens are dest classifiers and/or roots."
    )
    parser.add_argument("tokens", nargs="*", help="Dest classifiers and/or paths")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory")
    parser.add_argument(
        "--dest",
        action="append",
        default=[],
        help="Dest classifier (repeatable). Same tokens as positional dests.",
    )
    parser.add_argument("--max-shards", type=int, default=MAX_SHARDS)
    parser.add_argument(
        "--locales",
        default="",
        help="Comma-separated locales to require (overrides detection).",
    )
    parser.add_argument("--source-locale", default="", help="Source locale (default: detected, else en)")
    args = parser.parse_args()

    cwd = Path(args.cwd).expanduser().resolve()
    dests, requested = parse_tokens(args.tokens, cwd)
    for raw in args.dest:
        for part in raw.split(","):
            if part and not add_dest(dests, part):
                print(f"discover-copy-shards: unknown dest: {part}", file=sys.stderr)
    if not dests:
        dests.update(DEFAULT_DESTS)

    roots = resolve_roots(cwd, requested)

    tagged_by_root: list[list[tuple[Path, str]]] = []
    catalog_paths: list[Path] = []
    git_roots: list[str] = []
    for root in roots:
        tagged, catalog_files = iter_files(root, dests)
        tagged_by_root.append(tagged)
        catalog_paths.extend(catalog_files)
        git = git_root_of(root)
        if git is not None:
            git_roots.append(str(git))

    counts = [max(len(tagged), 1) for tagged in tagged_by_root]
    weight_total = sum(counts)
    leftover = args.max_shards
    all_shards: list[dict] = []

    # Leftover follows shards actually emitted, not the pre-walk allocation.
    for index, root in enumerate(roots):
        if index == len(roots) - 1:
            budget = leftover
        else:
            budget = max(1, (args.max_shards * counts[index]) // weight_total)
            budget = min(budget, leftover)
        if budget < 1:
            budget = 1
        shards = group_shards(root, tagged_by_root[index], budget)
        all_shards.extend(shards)
        leftover = max(0, args.max_shards - len(all_shards))
    all_shards = carve_overlaps(merge_equal_paths(all_shards))

    catalogs = unique([str(path) for path in catalog_paths])
    detected, source = detect_locales([Path(p) for p in catalogs])
    if args.source_locale:
        source = args.source_locale
    strict = bool(args.locales)
    if args.locales:
        locales = [item.strip() for item in args.locales.split(",") if item.strip()]
        if source and source not in locales:
            locales.insert(0, source)
    else:
        locales = detected
    if not source:
        source = locales[0] if locales else "en"
    if not locales:
        locales = [source]

    unique_git = unique(git_roots)
    payload = {
        "workspace": str(cwd),
        "dests": sorted(dests),
        "roots": [str(path) for path in roots],
        "shards": all_shards,
        "catalogs": catalogs,
        "git_roots": unique_git,
        "locales": locales,
        "source_locale": source,
        # strict: every catalog must carry every locale (user passed --locales).
        # Otherwise each catalog family only completes the locales it already ships.
        "strict_locales": strict,
        "checks": [detect_checks(Path(root)) for root in unique_git],
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
