# Second reader

An optional second model that reviews catalog copy next to the reviewing agent — a different model family catches a different class of mistake. It was field-tested on a 4,138-key, 13-locale Apple-platform catalog with Gemini 4 Argon through OpenCode Go: about 60 batch calls for the whole zh-Hans / zh-Hant pass, 2,000+ changes, and every disagreement settled in two rounds.

Use it only when the user asks for one, or names a model to consult.

## How to call it

`scripts/second-reader.py` talks to a local `opencode serve` and calls its `generate` endpoint: transient text, **no tools, no repository access, no session history**. The second reader cannot wander the codebase, so it costs exactly the batch you send.

```bash
opencode serve --hostname 127.0.0.1 --port 47123 > serve.log 2>&1 &
python3 scripts/second-reader.py prompt.txt --name shard-03
```

Each parallel agent passes its own `--name`. Stop the server when the run ends.

## What to send

- One batch = 60–90 keys. Send the source plus the locale(s) under review only — not the other locales, not code.
- Add one line of context where the string alone misleads: "button", "%@ is a field label such as Support URL", "status badge".
- Send your own verdict with the batch and ask the reader to agree, object, or add. One round then settles most items.
- Ask for compact JSON listing only the items with a problem.

## Disagreements

1. Collect the items you disagree on. Send them back together with the call-site context you found and your reasoning. The reader is stateless: repeat the earlier rounds' points in each new prompt.
2. At most three rounds per item.
3. If the reader still holds its position after three rounds and its point is not a factual error (wrong term, broken placeholder, misread meaning), lean toward adopting it.
4. Persistence is not evidence. **A platform term is settled by the platform's own documentation**, never by either model's memory. In the field run the reader insisted twice that App Store Connect's zh-Hans field is 宣传文本; Apple's help page says 推广文本. Both models also agreed on several Taiwan terms that Apple's /tw/ help pages contradict (see the playbook's official-term table).
5. Record every rejected suggestion with its reason. The next run reads it.

## What it was good and bad at

- Good: colloquial and translation-ese phrasing, missing measure words and units, placeholder adjacency, zh-Hans/zh-Hant drift, real mistranslations.
- Bad: anything that needs the call site (it cannot see that "call" is an AI call, that "Passwords" is the app's own page, or that a placeholder receives an already-localized label), and exact Apple term names.
