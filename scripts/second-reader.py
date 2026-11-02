#!/usr/bin/env python3
"""Ask a second model one stateless question through a local opencode server.

The second reader sees only the prompt: no tools, no repository, no history.
Each call goes to POST /api/session/{id}/generate, which returns text without
running the agent loop, so a batch of copy costs what the batch says and no
more. A multi-round discussion is the caller's job: put the earlier rounds'
points into the next prompt.

Start the server once (it prints its password on stdout):

    opencode serve --hostname 127.0.0.1 --port 47123 > serve.log 2>&1 &

Then:

    second-reader.py PROMPT_FILE|- --name shard-03 [--out FILE]

Environment:
    OPENCODE_URL       default http://127.0.0.1:47123
    OPENCODE_PASSWORD  server password; else read from OPENCODE_SERVE_LOG
    OPENCODE_SERVE_LOG path of the `opencode serve` output (default ./serve.log)
    SECOND_READER_MODEL provider/model, default opencode-go/gemini-4-argon
    SECOND_READER_STATE directory for per-name session ids and the usage log
                        (default ./.second-reader)

--name gives each caller its own session, so parallel agents never share one.
Every call appends a line to <state>/usage.log (name, prompt and reply size).
"""
import base64
import json
import os
import sys
import time
import urllib.request

URL = os.environ.get("OPENCODE_URL", "http://127.0.0.1:47123").rstrip("/") + "/api"
STATE = os.environ.get("SECOND_READER_STATE", ".second-reader")
MODEL = os.environ.get("SECOND_READER_MODEL", "opencode-go/gemini-4-argon")


def password():
    if os.environ.get("OPENCODE_PASSWORD"):
        return os.environ["OPENCODE_PASSWORD"]
    log = os.environ.get("OPENCODE_SERVE_LOG", "serve.log")
    with open(log) as f:
        for line in f:
            if line.startswith("server password"):
                return line.split()[2]
    raise SystemExit(f"no server password in {log}; is `opencode serve` running?")


def call(method, path, body=None, timeout=600):
    auth = base64.b64encode(f"opencode:{password()}".encode()).decode()
    req = urllib.request.Request(
        URL + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"content-type": "application/json", "authorization": "Basic " + auth},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def session_id(name):
    os.makedirs(STATE, exist_ok=True)
    path = os.path.join(STATE, f"session-{name}.txt")
    if os.path.exists(path):
        return open(path).read().strip()
    provider, model = MODEL.split("/", 1)
    empty = os.path.join(os.path.abspath(STATE), "empty")
    os.makedirs(empty, exist_ok=True)
    data = call("POST", "/session", {
        "title": f"second-reader-{name}",
        "model": {"providerID": provider, "id": model},
        "location": {"directory": empty},
        "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
    })["data"]
    with open(path, "w") as f:
        f.write(data["id"])
    return data["id"]


def take(args, flag, default=None):
    if flag in args:
        i = args.index(flag)
        value = args[i + 1]
        del args[i:i + 2]
        return value
    return default


def main():
    args = sys.argv[1:]
    out = take(args, "--out")
    name = take(args, "--name", "default")
    if not args:
        raise SystemExit(__doc__)
    prompt = sys.stdin.read() if args[0] == "-" else open(args[0]).read()
    sid = session_id(name)
    last = None
    for attempt in range(4):
        try:
            started = time.time()
            text = call("POST", f"/session/{sid}/generate", {"prompt": prompt})["data"]["text"]
            with open(os.path.join(STATE, "usage.log"), "a") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {name} in_chars={len(prompt)} "
                        f"out_chars={len(text)} secs={time.time() - started:.0f}\n")
            if out:
                with open(out, "w") as f:
                    f.write(text)
            print(text)
            return
        except Exception as error:  # rate limit or network: back off, retry
            last = error
            time.sleep(15 * (attempt + 1))
    raise SystemExit(f"second reader failed: {last}")


if __name__ == "__main__":
    main()
