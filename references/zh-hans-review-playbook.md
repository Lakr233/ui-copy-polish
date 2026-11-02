# zh-Hans deep-review playbook

A field-tested procedure for a dedicated review pass over shipped Simplified Chinese catalogs — after the localize phase has filled the gaps, or whenever the user asks to 检查中文翻译. It was distilled from a full review of a two-catalog Apple-platform project (~1,440 zh-Hans entries, 137 wording fixes, zero regressions).

Read the zh-Hans section of `copy-bar.md` first; this playbook extends it with procedure, not a different bar.

## 0. Ground rules

- Edit values, never keys, in the review pass.
- One locale per pass. Other locales are read-only witnesses.
- Record deliberate keeps and user preferences as you go. A preference that overrules the glossary (for example, 您 in permission prompts where the app body uses 你) is a finding about *you*, not the catalog — ask, then stop "fixing" it.
- Report before editing when the user asked for a report; edit before reporting when they asked for a fix.

## 1. Build the term ledger before touching anything

Dump every key → zh pair and read them all. Then list every term that has competitors, with counts:

| Concept | Stray | Dominant | Keep |
| --- | --- | --- | --- |
| guest (VM) | 客体 ×76 | 客户机 ×39 | 客户机 |
| Copy | 复制 ×26 | 拷贝 ×25 | 拷贝 (Apple) |
| Save | 保存 ×7 | 存储 ×9 | 存储 (Apple) |
| Filter | 过滤 ×4 | 筛选 ×7 | 筛选 (Apple) |
| load | 加载 ×3 | 载入 ×28 | 载入 |
| restart | 重新启动 ×7 | 重启 ×23 | 重启 |
| machines | 机器 ×5 | 虚拟机 ×16 | 虚拟机 |

Tie-break order: platform glossary > in-repo majority > shorter form. For Apple platforms the glossary is Apple's own zh-Hans UI: 拷贝、存储、筛选、载入、访达、钥匙串、描述文件、宗卷、设置助理、快速查看、聚焦、开发者工具.

A stray that is 30–50% of the total means earlier translators never agreed; those are the highest-visibility fixes.

**Look the platform term up; do not vote on it.** A catalog majority, the reviewing agent and a second model can all agree and still be wrong. On Apple platforms the App Store Connect help is published per locale — `developer.apple.com/cn/help/app-store-connect/…` (zh-Hans) and `/tw/help/…` (zh-Hant) — and its field and status names are the ones users see next to your app. Fetch the page; quote it in the ledger. Terms verified there on 2026-11-02:

| en | zh-Hans | zh-Hant |
| --- | --- | --- |
| Promotional Text | 推广文本 | 行銷宣傳文字 |
| Support URL / Marketing URL | 技术支持网址 / 营销网址 | 支援 URL / 行銷 URL |
| What's New in This Version | 此版本的新增内容 | 此版本的新增功能 |
| Screenshots / App Previews | 截屏 / App 预览 | 截圖 / App 預覽 |
| metadata | 元数据 | 後設資料 |
| build | 构建版本 | 建置版本 |
| App Review | App 审核 | App 審查 |
| Availability | 销售范围 | 供應狀況 |
| Win-back offer | 回头客优惠 | 舊客戶優惠 |
| Introductory / promotional offer | 推介促销优惠 / 促销优惠 | 試賣優惠 / 促銷優惠 |
| Offer code / subscription group | 优惠代码 / 订阅群组 | 優惠碼 / 訂閱群組 |
| Waiting for Review / In Review | 正在等待审核 / 正在审核 | 正在等待審查 / 審查中 |
| Rejected / Metadata Rejected | 被拒绝 / 元数据被拒绝 | 已拒絕 / 後設資料被拒絕 |
| Ready for Distribution / Pending Developer Release | 可分发 / 等待开发者发布 | 已可發佈 / 等待開發者發佈 |

In the field run the in-repo majority and both models had chosen 宣传文本, 上架范围, 挽回优惠 / 赢回优惠, 螢幕截圖, 上架範圍, 推介優惠 and 中繼資料 — every one contradicted by the help pages. Save is the same story outside App Store Connect: the catalog majority was 保存, Apple's menus say 存储.

## 2. Run the cheap audits before and after

Each is a few lines of Python over the parsed catalog. Run before (to find), after (to prove clean).

**Placeholder parity** — the multiset of format specifiers in each locale must match the source, with positional forms normalized (`%1$@` ≡ `%@`). Positional reordering in a translation is legal and often required; a missing or extra specifier is a crash or garbage output.

```python
import re
def specs(s):
    return [re.sub(r'^%(\d+\$)?', '%', m.group(0))
            for m in re.finditer(r'%(?:\d+\$)?(?:lld|llu|[@dDuUxXofegG])|%%', s)]
# sorted(specs(source)) == sorted(specs(value)) for every translated key
```

**Terminology strays** — recount the ledger terms; the loser count must be zero (or an approved keep).

**Cross-catalog identity** — the same source key in two catalogs must carry the same zh value (caught `OK` → 好 in one, 确定 in the other).

**CJK-adjacent placeholder spacing** — flag CJK directly touching a specifier, then whitelist the entries whose argument is itself a *localized* string (control names, category names). `正在设置%1$@…` with %1$@ = 音量 is correct without a space; `将于%@过期` with a date is not. Check the call site, not the pattern.

**Half-width punctuation next to CJK**, **keys with no localization at all** (whole features silently falling back to English — six strings in the field case), and **empty-string keys** round out the sweep.

## 2b. zh-Hant is its own locale

Review zh-Hant in the same pass but against its own ledger, not as a character conversion of zh-Hans. First decide whether the catalog is Taiwan or Hong Kong usage (count 專案 / 項目, 網路 / 網絡, 影片 / 視頻) and keep the majority. Taiwan Apple UI: 設定、檔案、伺服器、登入、帳號、訊息、建置版本、拷貝、儲存、檔案夾. Quotes are 「」 with 『』 nested. Then check that each zh-Hans / zh-Hant pair says the same thing — the field run found Hant strings still translating an older English value.

## 2c. The `en` value is not always the key

In `.xcstrings` the key is the code literal, but the English UI shows the `en` localization when it exists. Earlier polish passes edit `en` values (Title Case, "Unable to…"), so 10% of keys may carry an `en` value that differs from the key. Translate the `en` value — that is what English readers see — and treat an `en` value that breaks the copy bar (session, "Please … retry") as a finding of its own.

## 3. Back ambiguous keys with code, not guesses

A short key shared by two screens is a mistranslation trap:

- `Key` served both a plist-key field (键) and a keychain item class (密钥). The field said 密钥 while its own placeholder said 所有键. Fix: point the keychain call site at a new key (`Cryptographic Key`), inherit the other locales' neutral terms (キー / 키 / Khóa work for both senses), and let the generic key read 键.
- `Size` labeled screen dimensions in one panel (尺寸, correct) and file sizes in two tables (should be 大小). Same treatment: new `File Size` key for the tables.
- `Started` looked like a status; the call site formats a timestamp — 启动时间 was right all along. Verify before "fixing".

Rule: when one key serves two meanings, split it in code. Do not pick the translation of the more visible screen and let the other one stay wrong.

## 4. Edit `.xcstrings` surgically

Never re-serialize the whole file. Xcode's serialization has quirks a naive `json.dump` destroys, and a full rewrite turns a 150-line review diff into a 3,000-line reformat:

- Separator is `" : "` (space, colon, space); indent is two spaces; no trailing newline.
- An empty string entry serializes as `{\n\n    }` — not `{}`.
- Key order is the file's own; insert new keys next to their siblings.

Procedure: parse the JSON for navigation, locate each target entry by key, brace-match its span in the raw text, and replace only that entry's value bytes. Before the first edit, round-trip the file through your serializer and assert byte-identical output; if it differs, you are about to reformat the catalog.

Then verify with an AST-level diff against the base commit: existing keys must differ in the reviewed locale's values only, plus exactly the intended new keys. This is what proves ja/ko/vi were untouched.

## 5. Deliberate keeps are findings too

Write them down or the next reviewer re-litigates them:

- Community proper nouns stay untranslated: roothide、rootless、jbroot (translated once as 隐根/无根 — nobody could map them back).
- Apple official namings keep their shape: “文件”App、App Groups、App Store.
- Grammar distinctions survive: 已断开连接 (the disconnect *event*) vs 未连接 (the *state*).
- Context beats global uniformity when the contexts differ: patch enablement On = 启用, power toggle On/Off = 开/关.

## 6. Report shape

P0 outright mistranslations (wrong word, wrong context, missing strings) → P1 terminology unification (with counts) → P2 sentence-level polish and spacing. Every row: key, before, after, one-line reason. Keeps and preferences get their own section. The report is also the changelog for the review commit.
