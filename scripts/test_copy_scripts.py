#!/usr/bin/env python3
"""Behavior tests for discover-copy-shards and catalog-gaps."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(filename: str):
    path = HERE / filename
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


discover = load("discover-copy-shards.py")
gaps = load("catalog-gaps.py")


def touch(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ParseTokens(unittest.TestCase):
    def test_dest_alias_is_not_a_root(self):
        dests, roots = discover.parse_tokens(["code", "web"], Path("/tmp"))
        self.assertEqual(dests, {"code", "web"})
        self.assertEqual(roots, [])

    def test_all_expands(self):
        dests, _ = discover.parse_tokens(["all"], Path("/tmp"))
        self.assertEqual(dests, set(discover.ALL_DESTS))

    def test_missing_path_is_skipped(self):
        dests, roots = discover.parse_tokens(["/no/such/copy-root"], Path("/tmp"))
        self.assertEqual(dests, set())
        self.assertEqual(roots, [])


class Classify(unittest.TestCase):
    def test_catalog_wins(self):
        root = Path("/app")
        path = root / "Localizable.xcstrings"
        self.assertEqual(discover.classify(root, path, {"code", "catalog"}), "catalog")
        self.assertIsNone(discover.classify(root, path, {"code"}))

    def test_doc_only_when_dest_includes_doc(self):
        root = Path("/app")
        path = root / "docs" / "guide.md"
        self.assertEqual(discover.classify(root, path, {"doc"}), "doc")
        self.assertIsNone(discover.classify(root, path, {"code"}))

    def test_changelog_and_contributing_are_not_docs(self):
        root = Path("/app")
        self.assertIsNone(discover.classify(root, root / "CHANGELOG.md", {"doc"}))
        self.assertIsNone(discover.classify(root, root / "CONTRIBUTING.md", {"doc"}))
        self.assertEqual(discover.classify(root, root / "README.md", {"doc"}), "doc")

    def test_min_js_and_declarations_are_skipped(self):
        root = Path("/app")
        self.assertIsNone(discover.classify(root, root / "app.min.js", {"web", "code"}))
        self.assertIsNone(discover.classify(root, root / "types.d.ts", {"web", "code"}))
        self.assertIsNone(discover.classify(root, root / "Button.stories.tsx", {"web"}))
        self.assertIsNone(discover.classify(root, root / "Button.test.tsx", {"web"}))

    def test_api_dir_beats_web_suffix(self):
        root = Path("/app")
        path = root / "routes" / "login.ts"
        self.assertEqual(discover.classify(root, path, {"api", "web", "code"}), "api")
        self.assertEqual(discover.classify(root, root / "handlers" / "user.go", {"api", "code"}), "api")

    def test_code_is_fallback_for_many_languages(self):
        root = Path("/app")
        for name in ("Sources/App.swift", "src/main.rs", "cmd/root.go", "app/views.py", "lib/ui.dart", "Main.kt"):
            self.assertEqual(discover.classify(root, root / name, {"code"}), "code", name)
        self.assertIsNone(discover.classify(root, root / "Sources/App.swift", {"web"}))

    def test_catalog_detection_across_formats(self):
        self.assertTrue(discover.is_catalog(Path("/app/locales/en.json")))
        self.assertTrue(discover.is_catalog(Path("/app/config/locales/en.yml")))
        self.assertTrue(discover.is_catalog(Path("/app/res/values-zh-rCN/strings.xml")))
        self.assertTrue(discover.is_catalog(Path("/app/lib/l10n/intl_en.arb")))
        self.assertTrue(discover.is_catalog(Path("/app/en.lproj/Localizable.strings")))
        self.assertTrue(discover.is_catalog(Path("/app/Resources.zh-Hans.resx")))
        self.assertTrue(discover.is_catalog(Path("/app/po/de/LC_MESSAGES/app.po")))
        self.assertFalse(discover.is_catalog(Path("/app/package.json")))
        self.assertFalse(discover.is_catalog(Path("/app/res/layout/main.xml")))


class Locales(unittest.TestCase):
    def test_lproj_and_android(self):
        self.assertEqual(discover.locale_from_lproj("zh-Hans.lproj"), "zh-Hans")
        self.assertIsNone(discover.locale_from_lproj("Base.lproj"))
        self.assertEqual(discover.locale_from_android_values("values-zh-rCN"), "zh-CN")
        self.assertEqual(discover.locale_from_android_values("values-fr"), "fr")
        self.assertIsNone(discover.locale_from_android_values("values-night"))
        self.assertIsNone(discover.locale_from_android_values("values-w600dp"))

    def test_suffixed_names(self):
        self.assertEqual(discover.locale_from_suffixed_name("messages_zh_CN"), "zh_CN")
        self.assertEqual(discover.locale_from_suffixed_name("Resources.zh-Hans"), "zh-Hans")
        self.assertEqual(discover.locale_from_suffixed_name("intl_en"), "en")
        self.assertIsNone(discover.locale_from_suffixed_name("common"))

    def test_detect_from_xcstrings_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(
                root / "Localizable.xcstrings",
                json.dumps(
                    {
                        "sourceLanguage": "en",
                        "strings": {"Save": {"localizations": {"en": {}, "zh-Hans": {}, "ja": {}}}},
                    }
                ),
            )
            touch(root / "locales" / "fr.json", "{}")
            locales, source = discover.detect_locales(
                [root / "Localizable.xcstrings", root / "locales" / "fr.json"]
            )
            self.assertEqual(source, "en")
            self.assertEqual(locales[0], "en")
            self.assertEqual(set(locales), {"en", "zh-Hans", "ja", "fr"})

    def test_no_catalogs_means_no_locales(self):
        self.assertEqual(discover.detect_locales([]), ([], None))


class ShardDir(unittest.TestCase):
    def test_interface_module(self):
        root = Path("/app")
        file = root / "Interface" / "Settings" / "View.swift"
        shard_id, directory = discover.shard_dir(root, file, "code")
        self.assertEqual(shard_id, "code-ui-Settings")
        self.assertEqual(directory, root / "Interface" / "Settings")

    def test_monorepo_shards_per_app(self):
        root = Path("/repo")
        file = root / "apps" / "web" / "src" / "components" / "Button.tsx"
        shard_id, directory = discover.shard_dir(root, file, "web")
        self.assertEqual(shard_id, "web-web")
        self.assertEqual(directory, root / "apps" / "web")

    def test_go_cmd_and_rust_src(self):
        root = Path("/repo")
        self.assertEqual(discover.shard_dir(root, root / "cmd" / "cli" / "main.go", "code")[0], "code-cli")
        self.assertEqual(discover.shard_dir(root, root / "src" / "ui" / "mod.rs", "code")[0], "code-ui")

    def test_ui_anchor_under_generic_anchor_descends(self):
        root = Path("/app")
        shard_id, directory = discover.shard_dir(root, root / "App" / "Interface" / "Settings" / "View.swift", "code")
        self.assertEqual(shard_id, "code-ui-Settings")
        self.assertEqual(directory, root / "App" / "Interface" / "Settings")
        shard_id, directory = discover.shard_dir(root, root / "src" / "components" / "Button.tsx", "web")
        self.assertEqual(shard_id, "web-ui-components")
        self.assertEqual(directory, root / "src" / "components")

    def test_catalog_is_per_file(self):
        root = Path("/app")
        file = root / "Localizable.xcstrings"
        shard_id, directory = discover.shard_dir(root, file, "catalog")
        self.assertEqual(shard_id, "catalog-Localizable")
        self.assertEqual(directory, file)


class UniqueAndMerge(unittest.TestCase):
    def test_unique_keeps_order(self):
        self.assertEqual(discover.unique(["a", "b", "a", "c"]), ["a", "b", "c"])

    def test_group_shards_merges_same_family(self):
        root = Path("/app")
        files = [
            (root / "Sources" / "A" / "a.swift", "code"),
            (root / "Sources" / "B" / "b.swift", "code"),
            (root / "Sources" / "C" / "c.swift", "code"),
        ]
        shards = discover.group_shards(root, files, max_shards=1)
        self.assertEqual(len(shards), 1)
        self.assertEqual(shards[0]["dest"], "code")
        self.assertEqual(len(shards[0]["paths"]), 3)

    def test_carve_overlaps_excludes_nested_shard_paths(self):
        root = Path("/app")
        files = [
            (root / "App" / "Main.swift", "code"),
            (root / "App" / "Interface" / "Settings" / "View.swift", "code"),
        ]
        shards = discover.carve_overlaps(discover.group_shards(root, files, max_shards=12))
        by_id = {s["id"]: s for s in shards}
        self.assertEqual(by_id["code-app"]["paths"], ["/app/App"])
        self.assertEqual(by_id["code-app"]["exclude"], ["/app/App/Interface/Settings"])
        self.assertEqual(by_id["code-ui-settings"]["exclude"], [])

    def test_api_shard_sits_at_the_api_dir(self):
        root = Path("/repo")
        shard_id, directory = discover.shard_dir(root, root / "apps" / "web" / "src" / "pages" / "api" / "login.ts", "api")
        self.assertEqual(shard_id, "api-pages")
        self.assertEqual(directory, root / "apps" / "web" / "src" / "pages" / "api")
        shard_id, directory = discover.shard_dir(root, root / "rails" / "app" / "controllers" / "users_controller.rb", "api")
        self.assertEqual(shard_id, "api-app")
        self.assertEqual(directory, root / "rails" / "app" / "controllers")

    def test_equal_paths_merge_and_nested_api_is_excluded(self):
        root = Path("/repo")
        files = [
            (root / "apps" / "web" / "src" / "Button.tsx", "web"),
            (root / "apps" / "web" / "src" / "Native.swift", "code"),
            (root / "apps" / "web" / "src" / "pages" / "api" / "login.ts", "api"),
        ]
        shards = discover.carve_overlaps(discover.merge_equal_paths(discover.group_shards(root, files, max_shards=12)))
        self.assertEqual([s["id"] for s in shards], ["api-pages", "web-web"])
        web = shards[1]
        self.assertEqual(web["paths"], ["/repo/apps/web"])
        self.assertEqual(web["exclude"], ["/repo/apps/web/src/pages/api"])

    def test_collapse_nested(self):
        self.assertEqual(discover.collapse_nested(["/a/b", "/a", "/c"]), ["/a", "/c"])


class AddDest(unittest.TestCase):
    def test_unknown_token_rejected(self):
        dests: set[str] = set()
        self.assertFalse(discover.add_dest(dests, "./code"))
        self.assertEqual(dests, set())
        self.assertTrue(discover.add_dest(dests, "ui"))
        self.assertEqual(dests, {"code"})


class Checks(unittest.TestCase):
    def test_node_with_pnpm_and_typecheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root / "package.json", json.dumps({"scripts": {"lint": "eslint .", "typecheck": "tsc"}}))
            touch(root / "pnpm-lock.yaml")
            report = discover.detect_checks(root)
            self.assertIn("node", report["stack"])
            self.assertEqual(report["commands"], ["pnpm run typecheck"])

    def test_makefile_check_then_swift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root / "Makefile", "check:\n\t@true\ntest:\n\t@true\n")
            touch(root / "Package.swift")
            report = discover.detect_checks(root)
            self.assertEqual(report["commands"], ["make check", "swift build"])

    def test_xcode_without_makefile_has_note_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "App.xcodeproj").mkdir()
            report = discover.detect_checks(root)
            self.assertEqual(report["stack"], ["xcode"])
            self.assertEqual(report["commands"], [])
            self.assertTrue(report["notes"])

    def test_rust_go_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root / "Cargo.toml")
            touch(root / "go.mod")
            touch(root / "pyproject.toml")
            commands = discover.detect_checks(root)["commands"]
            self.assertIn("cargo check --quiet", commands)
            self.assertIn("go build ./...", commands)
            self.assertTrue(any(c.startswith("python3 -m compileall") for c in commands))


LOCALES = ["en", "zh-Hans"]


class XcstringsGaps(unittest.TestCase):
    def test_empty_value_is_a_gap_needs_review_with_value_is_not(self):
        catalog = {
            "strings": {
                "Empty": {
                    "localizations": {
                        "en": {"stringUnit": {"state": "translated", "value": ""}},
                        "zh-Hans": {"stringUnit": {"state": "translated", "value": "好"}},
                    }
                },
                "Present": {
                    "localizations": {
                        "en": {"stringUnit": {"state": "needs_review", "value": "Hello"}},
                        "zh-Hans": {"stringUnit": {"state": "translated", "value": "你好"}},
                    }
                },
                "Skip": {"shouldTranslate": False},
            }
        }
        self.assertEqual(gaps.catalog_gaps(catalog, LOCALES), [{"key": "Empty", "missing": ["en"]}])

    def test_empty_key_is_a_gap(self):
        result = gaps.catalog_gaps({"strings": {"": {}, "Ok": {}}}, LOCALES)
        self.assertEqual([g for g in result if g.get("issue") == "empty-key"], [{"key": "", "issue": "empty-key"}])
        # No en unit: the key "Ok" is its own English value. zh-Hans is still owed.
        self.assertEqual([g for g in result if g.get("key") == "Ok"], [{"key": "Ok", "missing": ["zh-Hans"]}])

    def test_missing_source_unit_means_key_is_the_value(self):
        catalog = {
            "sourceLanguage": "en",
            "strings": {
                "Close": {"localizations": {"zh-Hans": {"stringUnit": {"value": "关闭"}}}},
                "Open": {"localizations": {"en": {"stringUnit": {"value": ""}}, "zh-Hans": {"stringUnit": {"value": "打开"}}}},
            },
        }
        self.assertEqual(gaps.catalog_gaps(catalog, LOCALES), [{"key": "Open", "missing": ["en"]}])

    def test_plural_variations_count_as_present(self):
        catalog = {
            "strings": {
                "%lld items": {
                    "localizations": {
                        "en": {"variations": {"plural": {"one": {"stringUnit": {"value": "%lld item"}}, "other": {"stringUnit": {"value": "%lld items"}}}}},
                    }
                }
            }
        }
        self.assertEqual(gaps.catalog_gaps(catalog, ["en"]), [])

    def test_missing_file(self):
        report = gaps.report_for(Path("/no/such/catalog.xcstrings"), LOCALES)
        self.assertEqual(report["error"], "missing")
        self.assertEqual(report["gaps"], [])


class FamilyGaps(unittest.TestCase):
    def test_locale_dir_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            en = touch(root / "locales" / "en.json", json.dumps({"save": "Save", "nav": {"home": "Home"}}))
            zh = touch(root / "locales" / "zh-Hans.json", json.dumps({"save": "保存", "nav": {"home": ""}}))
            reports = gaps.build_reports([en, zh], ["en", "zh-Hans"], "en")
            self.assertEqual(len(reports), 1)
            report = reports[0]
            self.assertEqual(report["format"], "locale-dir")
            self.assertEqual(report["locales_present"], ["en", "zh-Hans"])
            self.assertEqual(report["gaps"], [{"key": "nav.home", "missing": ["zh-Hans"]}])

    def test_missing_locale_file_is_reported_only_when_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            en = touch(root / "locales" / "en.json", json.dumps({"save": "Save"}))
            strict = gaps.build_reports([en], ["en", "ja"], "en", strict=True)[0]
            self.assertEqual(strict["missing_files"], ["ja"])
            self.assertEqual(strict["gaps"], [{"key": "save", "missing": ["ja"]}])
            lax = gaps.build_reports([en], ["en", "ja"], "en", strict=False)[0]
            self.assertEqual(lax["locales_required"], ["en"])
            self.assertEqual(lax["gaps"], [])

    def test_xcstrings_lax_only_requires_shipped_locales(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = touch(
                Path(tmp) / "Localizable.xcstrings",
                json.dumps(
                    {
                        "sourceLanguage": "en",
                        "strings": {
                            "Save": {"localizations": {"zh-Hans": {"stringUnit": {"value": "保存"}}}},
                            "Delete": {"localizations": {"zh-Hans": {"stringUnit": {"value": ""}}}},
                        },
                    }
                ),
            )
            report = gaps.report_for(path, ["en", "zh-Hans", "ja"], "en", strict=False)
            self.assertEqual(report["locales_required"], ["en", "zh-Hans"])
            self.assertEqual(report["gaps"], [{"key": "Delete", "missing": ["zh-Hans"]}])

    def test_yaml_fallback_parser_reads_rails_locale(self):
        data = gaps.parse_simple_yaml(
            'en:\n  save: Save\n  nav:\n    home: "Home"  # comment\n    about: \'About\'\n  empty: ""\n  long: |\n    Two\n    lines\n  # comment\n  nil: ~\n'
        )
        self.assertEqual(
            data,
            {"en": {"save": "Save", "nav": {"home": "Home", "about": "About"}, "empty": "", "long": "Two lines", "nil": ""}},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            en = touch(root / "config" / "locales" / "en.yml", "en:\n  save: Save\n")
            ja = touch(root / "config" / "locales" / "ja.yml", "ja:\n  save: ''\n")
            report = gaps.build_reports([en, ja], ["en", "ja"], "en")[0]
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["gaps"], [{"key": "save", "missing": ["ja"]}])

    def test_android_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = touch(
                root / "res" / "values" / "strings.xml",
                '<resources><string name="save">Save</string><string name="app_id" translatable="false">x</string></resources>',
            )
            zh = touch(root / "res" / "values-zh-rCN" / "strings.xml", '<resources><string name="save"></string></resources>')
            report = gaps.build_reports([base, zh], ["en", "zh-CN"], "en")[0]
            self.assertEqual(report["format"], "android")
            self.assertEqual(report["gaps"], [{"key": "save", "missing": ["zh-CN"]}])

    def test_lproj_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            en = touch(root / "en.lproj" / "Localizable.strings", '"Save" = "Save";\n/* c */ "Delete" = "Delete";\n')
            zh = touch(root / "zh-Hans.lproj" / "Localizable.strings", '"Save" = "保存";\n')
            report = gaps.build_reports([en, zh], ["en", "zh-Hans"], "en")[0]
            self.assertEqual(report["format"], "lproj")
            self.assertEqual(report["gaps"], [{"key": "Delete", "missing": ["zh-Hans"]}])

    def test_arb_and_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            en = touch(root / "l10n" / "intl_en.arb", json.dumps({"@@locale": "en", "save": "Save", "@save": {}}))
            de = touch(root / "l10n" / "intl_de.arb", json.dumps({"@@locale": "de"}))
            report = gaps.build_reports([en, de], ["en", "de"], "en")[0]
            self.assertEqual(report["format"], "arb")
            self.assertEqual(report["gaps"], [{"key": "save", "missing": ["de"]}])

            base = touch(root / "i18n" / "messages.properties", "save=Save\ncancel=Cancel\n")
            zh = touch(root / "i18n" / "messages_zh_CN.properties", "save=保存\n")
            report = gaps.build_reports([base, zh], ["en", "zh_CN"], "en")[0]
            self.assertEqual(report["format"], "properties")
            self.assertEqual(report["gaps"], [{"key": "cancel", "missing": ["zh_CN"]}])

    def test_po_empty_and_fuzzy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            po = touch(
                root / "de" / "LC_MESSAGES" / "app.po",
                'msgid ""\nmsgstr "Content-Type: text/plain"\n\nmsgid "Save"\nmsgstr "Speichern"\n\nmsgid "Delete"\nmsgstr ""\n\n#, fuzzy\nmsgid "Retry"\nmsgstr "Wiederholen"\n',
            )
            report = gaps.build_reports([po], ["en", "de"], "en")[0]
            self.assertEqual(report["format"], "po")
            self.assertEqual(report["locales_present"], ["de"])
            self.assertEqual(sorted(g["key"] for g in report["gaps"]), ["Delete", "Retry"])

    def test_resx_and_xliff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = touch(root / "Resources.resx", '<root><data name="Save"><value>Save</value></data></root>')
            zh = touch(root / "Resources.zh-Hans.resx", '<root><data name="Save"><value></value></data></root>')
            report = gaps.build_reports([base, zh], ["en", "zh-Hans"], "en")[0]
            self.assertEqual(report["format"], "resx")
            self.assertEqual(report["gaps"], [{"key": "Save", "missing": ["zh-Hans"]}])

            xliff = touch(
                root / "ja.xliff",
                '<xliff version="1.2"><file source-language="en" target-language="ja"><body>'
                '<trans-unit id="Save"><source>Save</source><target>保存</target></trans-unit>'
                '<trans-unit id="Delete"><source>Delete</source><target></target></trans-unit>'
                "</body></file></xliff>",
            )
            report = gaps.build_reports([xliff], ["en", "ja"], "en")[0]
            self.assertEqual(report["format"], "xliff")
            self.assertEqual(report["gaps"], [{"key": "Delete", "missing": ["ja"]}])

    def test_parse_error_is_surfaced_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = touch(root / "locales" / "en.json", "{not json")
            report = gaps.build_reports([bad], ["en"], "en")[0]
            self.assertEqual(len(report["errors"]), 1)


class TranslationJobs(unittest.TestCase):
    def test_jobs_are_grouped_by_locale_and_chunked(self):
        items = []
        for index in range(120):
            items.append(
                {
                    "catalog": "/app/Localizable.xcstrings",
                    "format": "xcstrings",
                    "key": f"k{index}",
                    "source": f"S{index}",
                    "comment": "",
                    "locale": "ja",
                }
            )
        items.append(
            {
                "catalog": "/app/Localizable.xcstrings",
                "format": "xcstrings",
                "key": "only",
                "source": "Only",
                "comment": "",
                "locale": "zh-Hans",
            }
        )
        jobs = gaps.chunk_items(items, 100)
        self.assertEqual([job["id"] for job in jobs], ["ja-0", "ja-1", "zh-Hans-0"])
        self.assertEqual(jobs[0]["count"], 100)
        self.assertEqual(jobs[1]["count"], 20)
        self.assertEqual(jobs[2]["count"], 1)
        self.assertEqual(jobs[1]["items"][0]["key"], "k100")
        self.assertLessEqual(max(job["count"] for job in jobs), gaps.MAX_JOB_KEYS)

    def test_chunk_size_clamps_to_100(self):
        self.assertEqual(gaps.clamp_chunk_size(0), 1)
        self.assertEqual(gaps.clamp_chunk_size(500), 100)

    def test_emit_jobs_writes_manifest_and_skips_empty_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = touch(
                root / "Localizable.xcstrings",
                json.dumps(
                    {
                        "sourceLanguage": "en",
                        "strings": {
                            "": {"localizations": {"en": {"stringUnit": {"value": ""}}}},
                            "Save": {
                                "comment": "toolbar",
                                "localizations": {
                                    "en": {"stringUnit": {"value": "Save"}},
                                    "zh-Hans": {"stringUnit": {"value": ""}},
                                },
                            },
                            "Close": {"localizations": {"zh-Hans": {"stringUnit": {"value": "关闭"}}}},
                        },
                    }
                ),
            )
            jobs_dir = root / "jobs"
            items, empty_keys = gaps.collect_job_items([catalog], ["en", "zh-Hans"], "en", strict=False)
            self.assertEqual(empty_keys, [{"catalog": str(catalog), "key": ""}])
            self.assertEqual(
                items,
                [
                    {
                        "catalog": str(catalog),
                        "format": "xcstrings",
                        "key": "Save",
                        "source": "Save",
                        "comment": "toolbar",
                        "locale": "zh-Hans",
                    }
                ],
            )
            jobs = gaps.chunk_items(items, 100)
            manifest = gaps.write_jobs(jobs, jobs_dir, "en", empty_keys, [str(catalog)], 100)
            self.assertEqual(manifest["chunk_size"], 100)
            self.assertEqual(len(manifest["jobs"]), 1)
            job_path = Path(manifest["jobs"][0]["path"])
            payload = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["locale"], "zh-Hans")
            self.assertEqual(payload["items"][0]["source"], "Save")

    def test_locale_dir_jobs_carry_source_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            en = touch(root / "locales" / "en.json", json.dumps({"save": "Save", "home": "Home"}))
            zh = touch(root / "locales" / "zh-Hans.json", json.dumps({"save": "保存", "home": ""}))
            items, empty_keys = gaps.collect_job_items([en, zh], ["en", "zh-Hans"], "en", strict=False)
            self.assertEqual(empty_keys, [])
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["key"], "home")
            self.assertEqual(items[0]["source"], "Home")
            self.assertEqual(items[0]["locale"], "zh-Hans")


if __name__ == "__main__":
    unittest.main()
