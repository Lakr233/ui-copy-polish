#!/usr/bin/env python3
"""List incomplete keys across localization catalogs. Prints JSON on stdout.

Formats:

  .xcstrings                          Apple String Catalog (per-key locales)
  <lang>.lproj/*.strings|.stringsdict Apple legacy tables, grouped by table name
  res/values[-<lang>]/strings.xml     Android resources (also plurals/arrays)
  locales/<lang>.json|.yml            i18next / vue-i18n / Rails style, flat or
  locales/<lang>/<ns>.json|.yml       nested (keys flattened with dots)
  intl_<lang>.arb / app_<lang>.arb    Flutter ARB
  <base>.<lang>.resx                  .NET resources
  <base>_<lang>.properties            Java bundles
  <lang>/LC_MESSAGES/*.po, <lang>.po  gettext (empty or fuzzy msgstr)
  *.xliff / *.xlf                     empty <target>
  <lang>/*.ftl                        Fluent

Usage:

  catalog-gaps.py <catalog...> --locales en,zh-Hans [--source en] [--strict]
  catalog-gaps.py <catalog...> --locales en,zh-Hans --emit-jobs [--jobs-dir DIR] [--chunk-size 100]

Catalogs that belong to one family (same table across locale files) are
grouped, so a key present in en.json but absent from zh-Hans.json is a gap.
By default a family only has to complete the locales it already ships (plus
the source); --strict demands every --locales entry everywhere. Every report
has: format, paths, locales_present, locales_required, keys, gaps[], and
optional empty_key / missing_files / errors. JSON goes to stdout, a one-line
summary to stderr. `--emit-jobs` writes one JSON file per locale in chunks of
at most 100 keys and prints a manifest for translator subagents.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree

MAX_JOB_KEYS = 100

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
# Language segment is lowercase (zh, en, fil); region/script segments may be capitalised (CN, Hans).
LOCALE_RE = re.compile(r"^[a-z]{2,3}(?:[-_](?:[A-Za-z]{2,4}|\d{3}))?(?:[-_](?:[A-Za-z]{2}|\d{3}))?$")
NOT_LOCALES = {"base", "index", "app", "src", "lib", "res", "www", "api", "out", "web", "dev", "prod", "test", "main"}


def looks_like_locale(token: str) -> bool:
    return bool(LOCALE_RE.match(token)) and token.lower() not in NOT_LOCALES


def flatten(data, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (dict, list)):
                out.update(flatten(value, name))
            else:
                out[name] = "" if value is None else str(value)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            name = f"{prefix}[{index}]"
            if isinstance(value, (dict, list)):
                out.update(flatten(value, name))
            else:
                out[name] = "" if value is None else str(value)
    return out


# --- per-file parsers → {key: value} -----------------------------------------


def parse_json_table(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json5":
        text = re.sub(r"//[^\n]*", "", text)
        text = re.sub(r",\s*([}\]])", r"\1", text)
    return flatten(json.loads(text))


def parse_simple_yaml(text: str):
    """Locale-file YAML: nested maps, scalars, quoted strings, block scalars. No anchors/flow."""
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        index += 1
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if stripped.startswith("- "):
            continue  # lists carry no UI keys worth auditing
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip().strip("'\"")
        value = value.strip()
        if value in ("|", ">", "|-", ">-"):
            block: list[str] = []
            while index < len(lines):
                nxt = lines[index]
                if nxt.strip() and (len(nxt) - len(nxt.lstrip(" "))) <= indent:
                    break
                block.append(nxt.strip())
                index += 1
            parent[key] = " ".join(b for b in block if b)
            continue
        if value == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
            continue
        if value.startswith(("'", '"')):
            quote = value[0]
            end = 1
            while end < len(value):
                if value[end] == "\\" and quote == '"':
                    end += 2
                    continue
                if value[end] == quote:
                    if quote == "'" and end + 1 < len(value) and value[end + 1] == "'":
                        end += 2
                        continue
                    break
                end += 1
            inner = value[1:end]
            value = inner.replace('\\"', '"') if quote == '"' else inner.replace("''", "'")
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if value in ("~", "null"):
            value = ""
        parent[key] = value
    return root


def parse_yaml_table(path: Path, locale_hint: str | None) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
    except ImportError:
        data = parse_simple_yaml(text)
    # Rails: the whole file nests under its locale key.
    if isinstance(data, dict) and len(data) == 1:
        (only_key, inner), = data.items()
        if locale_hint and str(only_key) == locale_hint and isinstance(inner, dict):
            data = inner
    return flatten(data)


def parse_strings_table(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*//[^\n]*", "", text, flags=re.MULTILINE)
    out: dict[str, str] = {}
    for match in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', text):
        out[match.group(1)] = match.group(2)
    return out


def parse_stringsdict(path: Path) -> dict[str, str]:
    import plistlib

    data = plistlib.loads(path.read_bytes())
    return {str(key): "plural" for key in (data or {}).keys()}


def parse_android(path: Path) -> dict[str, str]:
    tree = ElementTree.parse(path)
    out: dict[str, str] = {}
    for node in tree.getroot():
        name = node.get("name")
        if not name or node.get("translatable") == "false":
            continue
        if node.tag == "string":
            out[name] = "".join(node.itertext()).strip()
        elif node.tag in {"plurals", "string-array"}:
            out[name] = "".join(node.itertext()).strip() or ""
    return out


def parse_arb(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: ("" if v is None else str(v)) for k, v in data.items() if not k.startswith("@")}


def parse_resx(path: Path) -> dict[str, str]:
    tree = ElementTree.parse(path)
    out: dict[str, str] = {}
    for node in tree.getroot().findall("data"):
        name = node.get("name")
        if not name or node.get("type"):
            continue
        value = node.find("value")
        out[name] = (value.text or "") if value is not None else ""
    return out


def parse_properties(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    pending = ""
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = pending + raw.strip()
        pending = ""
        if not line or line.startswith(("#", "!")):
            continue
        if line.endswith("\\"):
            pending = line[:-1]
            continue
        match = re.match(r"^([^=:\s]+)\s*[=:]?\s*(.*)$", line)
        if match:
            out[match.group(1)] = match.group(2)
    return out


def parse_po(path: Path) -> tuple[dict[str, str], list[str]]:
    """Return ({msgid: msgstr}, fuzzy_ids)."""
    out: dict[str, str] = {}
    fuzzy: list[str] = []
    current_id: list[str] | None = None
    current_str: list[str] | None = None
    is_fuzzy = False
    field = None

    def flush() -> None:
        nonlocal current_id, current_str, is_fuzzy
        if current_id is not None:
            msgid = "".join(current_id)
            if msgid != "":
                out[msgid] = "".join(current_str or [])
                if is_fuzzy:
                    fuzzy.append(msgid)
        current_id = None
        current_str = None
        is_fuzzy = False

    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            flush()
            field = None
            continue
        if line.startswith("#"):
            if line.startswith("#,") and "fuzzy" in line:
                is_fuzzy = True
            continue
        if line.startswith("msgid_plural"):
            field = None
            continue
        if line.startswith("msgid "):
            flush() if current_id is not None else None
            current_id = [json.loads(line[6:].strip() or '""')]
            current_str = []
            field = "id"
            continue
        if line.startswith("msgstr"):
            body = line.split(" ", 1)[1] if " " in line else '""'
            if current_str is None:
                current_str = []
            if line.startswith("msgstr[") and line.startswith("msgstr[0]") is False:
                # Only the first plural form decides emptiness.
                field = None
                continue
            current_str.append(json.loads(body.strip()))
            field = "str"
            continue
        if line.startswith('"'):
            piece = json.loads(line)
            if field == "id" and current_id is not None:
                current_id.append(piece)
            elif field == "str" and current_str is not None:
                current_str.append(piece)
    flush()
    return out, fuzzy


def parse_xliff(path: Path) -> tuple[dict[str, str], str | None]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    locale = None
    match = re.search(r'(?:target-language|trgLang)="([^"]+)"', text)
    if match:
        locale = match.group(1)
    out: dict[str, str] = {}
    root = ElementTree.fromstring(text)
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag not in {"trans-unit", "unit"}:
            continue
        key = node.get("id") or node.get("resname") or ""
        target = None
        for child in node.iter():
            if child.tag.split("}")[-1] == "target":
                target = child
                break
        if not key:
            source = next((c for c in node.iter() if c.tag.split("}")[-1] == "source"), None)
            key = "".join(source.itertext()) if source is not None else ""
        if key:
            out[key] = "".join(target.itertext()).strip() if target is not None else ""
    return out, locale


def parse_ftl(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"^(-?[A-Za-z][A-Za-z0-9_-]*)\s*=\s*(.*)$", line)
        if match:
            out[match.group(1)] = match.group(2).strip()
    return out


# --- xcstrings (kept API-compatible with the old xcstrings-gaps.py) ----------


def localized_value(loc: dict) -> str:
    unit = loc.get("stringUnit") or {}
    if unit:
        return str(unit.get("value") or "")
    variations = loc.get("variations") or {}
    for group in variations.values():
        for variant in (group or {}).values():
            value = str(((variant or {}).get("stringUnit") or {}).get("value") or "")
            if value.strip():
                return value
    substitutions = loc.get("substitutions") or {}
    return "sub" if substitutions else ""


def required_locales(locales: list[str], present: set[str], source: str, strict: bool) -> list[str]:
    """Strict: every requested locale. Otherwise only the ones this catalog already ships."""
    if strict:
        return list(locales)
    return [code for code in locales if code == source or code in present]


def catalog_gaps(catalog: dict, locales: list[str], source: str | None = None, strict: bool = True) -> list[dict]:
    strings = catalog.get("strings") or {}
    present = {code for e in strings.values() for code in ((e or {}).get("localizations") or {})}
    source = source or catalog.get("sourceLanguage") or (locales[0] if locales else "en")
    locales = required_locales(locales, present, source, strict)
    gaps = []
    for key, entry in strings.items():
        if key == "":
            gaps.append({"key": "", "issue": "empty-key"})
            continue
        entry = entry or {}
        if entry.get("shouldTranslate") is False:
            continue
        locs = entry.get("localizations") or {}
        missing = []
        for locale in locales:
            if locale == source and locale not in locs:
                continue  # Apple: with no source unit, the key itself is the source value.
            if not localized_value(locs.get(locale) or {}).strip():
                missing.append(locale)
        if missing:
            gaps.append({"key": key, "missing": missing})
    return gaps


def report_for(path: Path, locales: list[str], source: str | None = None, strict: bool = True) -> dict:
    """Single .xcstrings report (legacy entry point)."""
    if not path.is_file():
        return {"path": str(path), "format": "xcstrings", "error": "missing", "gaps": []}
    catalog = json.loads(path.read_text(encoding="utf-8"))
    strings = catalog.get("strings") or {}
    present = sorted({code for e in strings.values() for code in ((e or {}).get("localizations") or {})})
    source = source or catalog.get("sourceLanguage") or (locales[0] if locales else "en")
    return {
        "path": str(path),
        "format": "xcstrings",
        "paths": [str(path)],
        "locales_present": present,
        "locales_required": required_locales(locales, set(present), source, strict),
        "keys": len(strings),
        "gaps": catalog_gaps(catalog, locales, source, strict),
    }


# --- family detection --------------------------------------------------------


def locale_of(path: Path) -> tuple[str | None, str, str]:
    """Return (locale or None for the source table, format, family_key)."""
    suffix = path.suffix
    name = path.name
    parts = path.parts
    if suffix == ".xcstrings":
        return None, "xcstrings", str(path)
    if suffix in {".strings", ".stringsdict"}:
        for index, part in enumerate(parts[:-1]):
            if part.endswith(".lproj"):
                code = part[: -len(".lproj")]
                family = str(Path(*parts[:index]) / name) if index else name
                return (None if code == "Base" else code), "lproj", family
        return None, "strings", str(path)
    if name in {"strings.xml", "plurals.xml", "arrays.xml"}:
        parent = path.parent.name
        family = str(path.parent.parent / name)
        if parent == "values":
            return None, "android", family
        if parent.startswith("values-"):
            rest = parent[len("values-") :]
            if rest.startswith("b+"):
                code = rest[2:].replace("+", "-")
            else:
                bits = rest.split("-")
                code = bits[0]
                if len(bits) > 1 and bits[1].startswith("r"):
                    code += "-" + bits[1][1:]
            return code, "android", family
    if suffix == ".arb":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            code = data.get("@@locale")
        except (OSError, ValueError):
            code = None
        if not code:
            code = suffixed_locale(path.stem)
        return code, "arb", str(path.parent)
    if suffix == ".resx":
        code = suffixed_locale(path.stem)
        base = path.stem.rsplit(".", 1)[0] if code else path.stem
        return code, "resx", str(path.parent / base)
    if suffix == ".properties":
        code = suffixed_locale(path.stem)
        base = path.stem[: -(len(code) + 1)] if code else path.stem
        return code, "properties", str(path.parent / base)
    if suffix in {".po", ".pot"}:
        code = None
        for part in reversed(parts[:-1]):
            if looks_like_locale(part):
                code = part
                break
        if code is None and suffix == ".po" and looks_like_locale(path.stem):
            code = path.stem
        return (None if suffix == ".pot" else code), "po", str(path)
    if suffix in {".xliff", ".xlf"}:
        return None, "xliff", str(path)
    if suffix == ".ftl":
        for part in reversed(parts[:-1]):
            if looks_like_locale(part):
                return part, "ftl", str(path.parent.parent / name)
        return None, "ftl", str(path)
    if suffix in {".json", ".json5", ".yml", ".yaml", ".toml"}:
        if looks_like_locale(path.stem):
            return path.stem, "locale-dir", str(path.parent / f"*{suffix}")
        for index in range(len(parts) - 2, -1, -1):
            part = parts[index]
            if part in LOCALE_DIR_NAMES:
                break
            if looks_like_locale(part):
                rel = Path(*parts[index + 1 :])
                return part, "locale-dir", str(Path(*parts[:index]) / "*" / rel)
        return None, "locale-dir", str(path)
    return None, "unknown", str(path)


def suffixed_locale(stem: str) -> str | None:
    for sep in (".", "_"):
        if sep in stem:
            head, tail = stem.rsplit(sep, 1)
            if looks_like_locale(tail):
                return tail
            if sep == "_" and "_" in head:
                _, mid = head.rsplit("_", 1)
                candidate = f"{mid}_{tail}"
                if looks_like_locale(candidate):
                    return candidate
    return None


def load_table(path: Path, fmt: str, locale: str | None) -> tuple[dict[str, str], dict]:
    extra: dict = {}
    if fmt == "lproj" or fmt == "strings":
        if path.suffix == ".stringsdict":
            return parse_stringsdict(path), extra
        return parse_strings_table(path), extra
    if fmt == "android":
        return parse_android(path), extra
    if fmt == "arb":
        return parse_arb(path), extra
    if fmt == "resx":
        return parse_resx(path), extra
    if fmt == "properties":
        return parse_properties(path), extra
    if fmt == "po":
        table, fuzzy = parse_po(path)
        extra["fuzzy"] = fuzzy
        return table, extra
    if fmt == "xliff":
        table, code = parse_xliff(path)
        extra["locale"] = code
        return table, extra
    if fmt == "ftl":
        return parse_ftl(path), extra
    if fmt == "locale-dir":
        if path.suffix in {".yml", ".yaml"}:
            return parse_yaml_table(path, locale), extra
        if path.suffix == ".toml":
            try:
                import tomllib  # Python 3.11+
            except ImportError as exc:
                raise RuntimeError("TOML catalogs need Python 3.11+") from exc
            return flatten(tomllib.loads(path.read_text(encoding="utf-8"))), extra
        return parse_json_table(path), extra
    raise RuntimeError(f"unsupported catalog: {path}")


def report_family(
    fmt: str,
    family: str,
    members: list[tuple[Path, str | None]],
    locales: list[str],
    source: str,
    strict: bool = True,
) -> dict:
    report: dict = {"format": fmt, "family": family, "paths": [str(p) for p, _ in members], "gaps": [], "errors": []}
    tables: dict[str, dict[str, str]] = {}
    fuzzy_by_locale: dict[str, list[str]] = {}
    for path, locale in members:
        try:
            table, extra = load_table(path, fmt, locale)
        except Exception as exc:  # noqa: BLE001 - surface every parse failure
            report["errors"].append(f"{path}: {exc}")
            continue
        code = locale or extra.get("locale") or source
        tables.setdefault(code, {}).update(table)
        if extra.get("fuzzy"):
            fuzzy_by_locale.setdefault(code, []).extend(extra["fuzzy"])
    report["locales_present"] = sorted(tables)

    if fmt in {"po", "xliff"}:
        # Single-locale files: a gap is an empty (or fuzzy) target.
        all_keys: set[str] = set()
        for code, table in tables.items():
            fuzzy = set(fuzzy_by_locale.get(code, []))
            for key, value in table.items():
                all_keys.add(key)
                if not value.strip() or key in fuzzy:
                    report["gaps"].append({"key": key, "missing": [code]})
        report["keys"] = len(all_keys)
        return report

    all_keys = set()
    for table in tables.values():
        all_keys.update(table)
    if "" in all_keys:
        report["empty_key"] = True
        report["gaps"].append({"key": "", "issue": "empty-key"})
        all_keys.discard("")
    required = required_locales(locales, set(tables), source, strict)
    report["locales_required"] = required
    missing_files = [code for code in required if code not in tables]
    if missing_files:
        report["missing_files"] = missing_files
    for key in sorted(all_keys):
        missing = [code for code in required if not (tables.get(code, {}).get(key) or "").strip()]
        if missing:
            report["gaps"].append({"key": key, "missing": missing})
    report["keys"] = len(all_keys)
    return report


def build_reports(paths: list[Path], locales: list[str], source: str, strict: bool = True) -> list[dict]:
    reports: list[dict] = []
    families: dict[tuple[str, str], list[tuple[Path, str | None]]] = {}
    for path in paths:
        if not path.is_file():
            reports.append({"path": str(path), "error": "missing", "gaps": []})
            continue
        if path.suffix == ".xcstrings":
            try:
                reports.append(report_for(path, locales, source, strict))
            except ValueError as exc:
                reports.append({"path": str(path), "format": "xcstrings", "error": str(exc), "gaps": []})
            continue
        locale, fmt, family = locale_of(path)
        families.setdefault((fmt, family), []).append((path, locale))
    for (fmt, family), members in sorted(families.items()):
        reports.append(report_family(fmt, family, members, locales, source, strict))
    return reports


def clamp_chunk_size(value: int) -> int:
    if value < 1:
        return 1
    return min(value, MAX_JOB_KEYS)


def source_from_xcstrings(entry: dict, source: str, key: str) -> tuple[str, str]:
    comment = str(entry.get("comment") or "")
    value = localized_value((entry.get("localizations") or {}).get(source) or {})
    if value.strip():
        return value, comment
    return key, comment


def source_from_tables(tables: dict[str, dict[str, str]], source: str, key: str) -> str:
    value = (tables.get(source) or {}).get(key) or ""
    if value.strip():
        return value
    for table in tables.values():
        other = table.get(key) or ""
        if other.strip():
            return other
    return key


def tables_for_family(fmt: str, members: list[tuple[Path, str | None]], source: str) -> dict[str, dict[str, str]]:
    tables: dict[str, dict[str, str]] = {}
    for path, locale in members:
        try:
            table, extra = load_table(path, fmt, locale)
        except Exception:  # noqa: BLE001 - skip unreadable members; reports already surface errors
            continue
        code = locale or extra.get("locale") or source
        tables.setdefault(code, {}).update(table)
    return tables


def collect_job_items(paths: list[Path], locales: list[str], source: str, strict: bool) -> tuple[list[dict], list[dict]]:
    """One item per (key, missing locale). Empty-string keys are listed separately for the merger."""
    items: list[dict] = []
    empty_keys: list[dict] = []
    reports = build_reports(paths, locales, source, strict)
    families: dict[tuple[str, str], list[tuple[Path, str | None]]] = {}
    for path in paths:
        if not path.is_file() or path.suffix == ".xcstrings":
            continue
        locale, fmt, family = locale_of(path)
        families.setdefault((fmt, family), []).append((path, locale))

    family_tables: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    for key, members in families.items():
        family_tables[key] = tables_for_family(key[0], members, source)

    for report in reports:
        fmt = report.get("format")
        if report.get("error") or not fmt:
            continue
        if fmt == "xcstrings":
            catalog_path = report.get("path") or (report.get("paths") or [""])[0]
            try:
                catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            strings = catalog.get("strings") or {}
            for gap in report.get("gaps") or []:
                key = gap.get("key", "")
                if gap.get("issue") == "empty-key" or key == "":
                    empty_keys.append({"catalog": catalog_path, "key": ""})
                    continue
                entry = strings.get(key) or {}
                source_text, comment = source_from_xcstrings(entry, source, key)
                for locale in gap.get("missing") or []:
                    items.append(
                        {
                            "catalog": catalog_path,
                            "format": "xcstrings",
                            "key": key,
                            "source": source_text,
                            "comment": comment,
                            "locale": locale,
                        }
                    )
            continue

        family = report.get("family") or ""
        tables = family_tables.get((fmt, family), {})
        catalog_path = (report.get("paths") or [family])[0]
        for gap in report.get("gaps") or []:
            key = gap.get("key", "")
            if gap.get("issue") == "empty-key" or key == "":
                empty_keys.append({"catalog": catalog_path, "key": ""})
                continue
            source_text = source_from_tables(tables, source, key)
            for locale in gap.get("missing") or []:
                items.append(
                    {
                        "catalog": catalog_path,
                        "format": fmt,
                        "family": family,
                        "key": key,
                        "source": source_text,
                        "comment": "",
                        "locale": locale,
                    }
                )
    items.sort(key=lambda row: (row["locale"], row.get("catalog") or "", row.get("key") or ""))
    return items, empty_keys


def chunk_items(items: list[dict], chunk_size: int) -> list[dict]:
    """Group by locale, then split each locale into chunks of at most chunk_size keys."""
    size = clamp_chunk_size(chunk_size)
    by_locale: dict[str, list[dict]] = {}
    for item in items:
        by_locale.setdefault(item["locale"], []).append(item)
    jobs: list[dict] = []
    for locale in sorted(by_locale):
        rows = by_locale[locale]
        for index in range(0, len(rows), size):
            chunk = rows[index : index + size]
            jobs.append(
                {
                    "id": f"{locale}-{index // size}",
                    "locale": locale,
                    "chunk": index // size,
                    "count": len(chunk),
                    "items": chunk,
                }
            )
    return jobs


def write_jobs(
    jobs: list[dict],
    jobs_dir: Path,
    source: str,
    empty_keys: list[dict],
    catalogs: list[str],
    chunk_size: int,
) -> dict:
    jobs_dir.mkdir(parents=True, exist_ok=True)
    manifest_jobs: list[dict] = []
    for job in jobs:
        name = f"job-{job['id']}.json"
        path = jobs_dir / name
        payload = {
            "id": job["id"],
            "locale": job["locale"],
            "chunk": job["chunk"],
            "source_locale": source,
            "items": job["items"],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest_jobs.append(
            {
                "id": job["id"],
                "locale": job["locale"],
                "chunk": job["chunk"],
                "path": str(path),
                "count": job["count"],
            }
        )
    manifest = {
        "source": source,
        "chunk_size": chunk_size,
        "work_dir": str(jobs_dir),
        "jobs": manifest_jobs,
        "catalogs": catalogs,
        "empty_keys": empty_keys,
    }
    (jobs_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalogs", nargs="+")
    parser.add_argument("--locales", default="en", help="Comma-separated locales to complete")
    parser.add_argument("--source", default="", help="Source locale (default: first of --locales)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require every --locales entry in every catalog. Default: each catalog only completes the locales it already ships.",
    )
    parser.add_argument(
        "--emit-jobs",
        action="store_true",
        help="Write per-locale translation jobs (max 100 keys each) and print a manifest. Translators read the job files; they do not edit catalogs.",
    )
    parser.add_argument(
        "--jobs-dir",
        default="",
        help="Directory for --emit-jobs files (default: a new temp directory).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=MAX_JOB_KEYS,
        help=f"Keys per translation job (default {MAX_JOB_KEYS}, max {MAX_JOB_KEYS}).",
    )
    args = parser.parse_args()
    locales = [item.strip() for item in args.locales.split(",") if item.strip()]
    source = args.source or (locales[0] if locales else "en")
    paths = [Path(raw).expanduser() for raw in args.catalogs]
    if args.emit_jobs:
        chunk_size = clamp_chunk_size(args.chunk_size)
        items, empty_keys = collect_job_items(paths, locales, source, args.strict)
        jobs = chunk_items(items, chunk_size)
        jobs_dir = Path(args.jobs_dir).expanduser() if args.jobs_dir else Path(tempfile.mkdtemp(prefix="copy-jobs-"))
        manifest = write_jobs(jobs, jobs_dir, source, empty_keys, [str(p) for p in paths], chunk_size)
        json.dump(manifest, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        print(
            f"catalog-gaps: {len(jobs)} jobs, {len(items)} items, {len(empty_keys)} empty keys",
            file=sys.stderr,
        )
        return 0
    reports = build_reports(paths, locales, source, args.strict)
    json.dump(reports, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    total = sum(len(r.get("gaps") or []) for r in reports)
    errors = sum(len(r.get("errors") or []) + (1 if r.get("error") else 0) for r in reports)
    print(f"catalog-gaps: {total} gaps, {errors} errors", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
