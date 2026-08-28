let meta = #{
    name: "ui-copy-polish",
    description: "Polish user-facing UI copy: find, verify, fix, review loop, localize, commit, push",
    when_to_use: "When the user wants to polish UI copy or runs /ui-copy-polish",
    phases: [
        #{ title: "Find", detail: "scan each shard for UI copy that fails the bar" },
        #{ title: "Verify", detail: "independently confirm each finding" },
        #{ title: "Fix", detail: "apply confirmed rewrites" },
        #{ title: "Review", detail: "review edits and loop until clean" },
        #{ title: "Localize", detail: "complete every locale in every catalog" },
        #{ title: "Ship", detail: "cheap checks, commit by pathspec, push" },
    ],
};

let finding_item = #{
    "type": "object",
    "required": ["file", "line", "current", "reason", "text", "translations"],
    "properties": #{
        "file": #{ "type": "string" },
        "line": #{ "type": "integer" },
        "current": #{ "type": "string" },
        "reason": #{ "type": "string" },
        "text": #{ "type": "string" },
        "translations": #{ "type": "object", "additionalProperties": #{ "type": "string" } },
        "kind": #{ "type": "string" },
    },
};

let findings_schema = #{
    "type": "object",
    "required": ["findings"],
    "properties": #{
        "findings": #{ "type": "array", "maxItems": 20, "items": finding_item },
    },
};

let confirmed_schema = #{
    "type": "object",
    "required": ["confirmed"],
    "properties": #{
        "confirmed": #{ "type": "array", "maxItems": 20, "items": finding_item },
    },
};

let fix_schema = #{
    "type": "object",
    "required": ["changed_files", "applied"],
    "properties": #{
        "changed_files": #{ "type": "array", "items": #{ "type": "string" } },
        "applied": #{ "type": "integer" },
        "skipped": #{ "type": "integer" },
        "new_keys": #{ "type": "array", "items": #{ "type": "string" } },
        "notes": #{ "type": "string" },
    },
};

let review_schema = #{
    "type": "object",
    "required": ["clean", "remaining"],
    "properties": #{
        "clean": #{ "type": "boolean" },
        "remaining": #{ "type": "array", "maxItems": 20, "items": finding_item },
    },
};

let localize_schema = #{
    "type": "object",
    "required": ["changed_files", "filled"],
    "properties": #{
        "changed_files": #{ "type": "array", "items": #{ "type": "string" } },
        "filled": #{ "type": "integer" },
        "notes": #{ "type": "string" },
    },
};

let ship_schema = #{
    "type": "object",
    "required": ["commits"],
    "properties": #{
        "commits": #{
            "type": "array",
            "items": #{
                "type": "object",
                "required": ["root", "sha", "pushed"],
                "properties": #{
                    "root": #{ "type": "string" },
                    "sha": #{ "type": "string" },
                    "files": #{ "type": "array", "items": #{ "type": "string" } },
                    "pushed": #{ "type": "boolean" },
                },
            },
        },
        "notes": #{ "type": "string" },
    },
};

fn join_bullets(items) {
    let out = "";
    let first = true;
    if items == () { return out; }
    for p in items {
        if !first { out += "\n"; }
        first = false;
        out += "- ";
        out += p;
    }
    out
}

fn join_plain(items, sep) {
    let out = "";
    let first = true;
    if items == () { return out; }
    for p in items {
        if !first { out += sep; }
        first = false;
        out += p;
    }
    out
}

fn has_prefix(file, prefix) {
    if file == () || prefix == () { return false; }
    if file == prefix { return true; }
    let n = prefix.len();
    if n == 0 { return false; }
    if file.len() < n { return false; }
    if file.sub_string(0, n) != prefix { return false; }
    file.sub_string(n, 1) == "/"
}

fn in_shard(shard, file) {
    if shard == () || file == () { return false; }
    if !has_prefix(file, shard.root) { return false; }
    if shard.exclude != () {
        for p in shard.exclude {
            if has_prefix(file, p) { return false; }
        }
    }
    if shard.paths == () || shard.paths.len() == 0 { return true; }
    for p in shard.paths {
        if has_prefix(file, p) { return true; }
    }
    false
}

fn push_unique(list, item) {
    if item == () || item == "" { return list; }
    for x in list {
        if x == item { return list; }
    }
    list.push(item);
    list
}

fn take(output, field) {
    if output == () { return []; }
    let v = output[field];
    if v == () { return []; }
    v
}

fn filter_to_shard(shard, items) {
    let kept = [];
    let dropped = 0;
    for f in items {
        if f != () && f.file != () && in_shard(shard, f.file) {
            kept.push(f);
        } else {
            dropped += 1;
        }
    }
    if dropped > 0 {
        log("dropped " + dropped.to_string() + " out-of-shard items from " + shard.id);
    }
    kept
}

fn read_intro(ctx, section) {
    let p = "";
    p += "This is a cold start. Read files and grep with your tools. Do not answer from memory.\n";
    p += "Read and obey:\n- ";
    p += ctx.copy_bar;
    p += "\n- ";
    p += ctx.roles;
    p += " (section ";
    p += section;
    p += ")\nIf you cannot read those files, return an empty result.\n";
    p += "SOURCE: ";
    p += ctx.source;
    p += "\nLOCALES: ";
    p += json_encode(ctx.locales);
    p += "\n";
    p
}

fn scope_lines(shard, verb) {
    let p = "\nSHARD: ";
    p += shard.id;
    p += "\nROOT: ";
    p += shard.root;
    p += "\nDEST: ";
    p += shard.dest;
    p += "\n";
    p += verb;
    p += " only these paths (recursive for directories). Do not go outside them:\n";
    p += join_bullets(shard.paths);
    if shard.exclude != () && shard.exclude.len() > 0 {
        p += "\nEXCLUDE — another shard owns these subpaths; skip them completely:\n";
        p += join_bullets(shard.exclude);
    }
    p
}

fn find_prompt(ctx, shard) {
    let p = read_intro(ctx, "Finder");
    p += scope_lines(shard, "Scan");
    p += "\n\nReturn at most 20 findings, worst first. An empty list is valid only after you grepped these paths for user-facing strings.";
    p
}

fn verify_prompt(ctx, shard, findings_json) {
    let p = read_intro(ctx, "Verifier");
    p += "\nSHARD: ";
    p += shard.id;
    p += "\nDEST: ";
    p += shard.dest;
    p += "\nIndependently verify these findings. Open each file. Keep only items that are user-visible, fail the bar, and keep meaning and tokens.\nJSON:\n";
    p += findings_json;
    p
}

fn fix_prompt(ctx, shard, findings_json) {
    let p = read_intro(ctx, "Fixer");
    p += scope_lines(shard, "Edit");
    if shard.dest != "catalog" {
        p += "\nDo NOT edit localization catalogs in this step — the localizer runs afterwards. Report new source-locale keys in new_keys.";
    }
    p += "\nApply only these confirmed findings.\nJSON:\n";
    p += findings_json;
    p
}

fn review_prompt(ctx, shard, files_json) {
    let p = read_intro(ctx, "Reviewer");
    p += "\nSHARD: ";
    p += shard.id;
    p += "\nDEST: ";
    p += shard.dest;
    p += "\nReview the edited files (read them and git diff them). Return remaining issues that still fail the bar. Do not restyle copy that now passes.\nFILES:\n";
    p += files_json;
    p
}

fn gaps_command(ctx) {
    if ctx.gaps_script == "" || ctx.catalogs.len() == 0 { return ""; }
    let cmd = "python3 " + json_encode(ctx.gaps_script) + " --locales " + join_plain(ctx.locales, ",") + " --source " + ctx.source;
    if ctx.strict { cmd += " --strict"; }
    for c in ctx.catalogs {
        cmd += " ";
        cmd += json_encode(c);
    }
    cmd
}

fn localize_prompt(ctx, new_keys) {
    let p = read_intro(ctx, "Localizer");
    p += "\nCATALOGS:\n";
    p += join_bullets(ctx.catalogs);
    p += "\nNEW KEYS FROM THIS RUN:\n";
    p += join_bullets(new_keys);
    let cmd = gaps_command(ctx);
    if cmd != "" {
        p += "\nRun this first, then fill every gap it lists, then run it again and report the result:\n";
        p += cmd;
    }
    if ctx.strict {
        p += "\nEvery catalog must carry every locale in LOCALES.";
    } else {
        p += "\nEach catalog completes the locales it already ships (its locales_required in the report). Do not add a locale to a catalog that does not have it.";
    }
    p += "\nAlso grep the sources under ";
    p += json_encode(ctx.git_roots);
    p += " for lookup keys missing from the catalogs and add them. Delete an empty-string \"\" key. Keep each file's existing formatting; no unrelated churn.";
    p
}

fn ship_prompt(ctx, changed) {
    let p = "";
    p += "This is a cold start. Use tools. Do not answer from memory.\n";
    p += "Read and obey the Shipper section of:\n";
    p += ctx.roles;
    p += "\nGIT ROOTS:\n";
    p += join_bullets(ctx.git_roots);
    p += "\nCHECKS:\n";
    if ctx.checks.len() == 0 { p += "(none listed)"; }
    for c in ctx.checks {
        p += "- ";
        p += c.root;
        p += "\n  stack: ";
        p += if c.stack == () { "unknown" } else { join_plain(c.stack, ", ") };
        p += "\n  commands: ";
        p += if c.commands == () || c.commands.len() == 0 { "(none)" } else { join_plain(c.commands, " && ") };
        p += "\n  notes: ";
        p += if c.notes == () { "-" } else { join_plain(c.notes, " ") };
        p += "\n";
    }
    let cmd = gaps_command(ctx);
    if cmd != "" {
        p += "\nCATALOG CHECK (must report zero errors):\n";
        p += cmd;
    }
    p += "\nCHANGED FILES FROM THIS RUN:\n";
    p += join_bullets(changed);
    p += "\nCOMMIT: ";
    p += if ctx.do_commit { "true" } else { "false" };
    p += "\nPUSH: ";
    p += if ctx.do_push { "true" } else { "false" };
    if ctx.trailers != "" {
        p += "\nAppend these trailer lines to the commit message:\n";
        p += ctx.trailers;
    }
    p += "\nCommit only the intersection of CHANGED FILES and git status --porcelain. Other dirty files belong to someone else — leave them unstaged and untouched. Never git add -A / -u / . and never commit -a. Never force-push.";
    p
}

fn set_items(work, i, items) {
    let w = work[i];
    w.items = items;
    work[i] = w;
    work
}

fn item_count(work) {
    let n = 0;
    for w in work { n += w.items.len(); }
    n
}

fn items_snapshot(work) {
    let out = [];
    for w in work { out.push(w.items); }
    out
}

fn collect_fix_outputs(results, changed, new_keys) {
    if results == () { return #{ changed: changed, new_keys: new_keys }; }
    for r in results {
        if r != () && r.success && r.output != () {
            for path in take(r.output, "changed_files") { changed = push_unique(changed, path); }
            for k in take(r.output, "new_keys") { new_keys = push_unique(new_keys, k); }
        }
    }
    #{ changed: changed, new_keys: new_keys }
}

fn fix_work(ctx, work, fix_schema, changed, new_keys) {
    let jobs = [];
    for w in work {
        if w.items.len() > 0 {
            jobs.push(#{
                prompt: fix_prompt(ctx, w.shard, json_encode(w.items)),
                label: "fix:" + w.shard.id,
                capability_mode: "read-write",
                output_schema: fix_schema,
            });
        }
    }
    if jobs.len() == 0 { return #{ changed: changed, new_keys: new_keys }; }
    collect_fix_outputs(parallel(jobs), changed, new_keys)
}

if args == () {
    pause("verification", "Pass args from scripts/discover-copy-shards.py plus copy_bar_path, roles_path, gaps_script.");
}

let copy_bar = args.copy_bar_path;
let roles = args.roles_path;
let shards = args.shards;
if copy_bar == () || copy_bar == "" || roles == () || roles == "" || shards == () {
    pause("verification", "Need args.copy_bar_path, args.roles_path, and args.shards.");
}
if shards.len() == 0 {
    complete(#{ summary: "No copy shards discovered.", commits: [] });
}

let locales = if args.locales == () || args.locales.len() == 0 { ["en"] } else { args.locales };
let ctx = #{
    copy_bar: copy_bar,
    roles: roles,
    catalogs: if args.catalogs == () { [] } else { args.catalogs },
    git_roots: if args.git_roots == () { [] } else { args.git_roots },
    checks: if args.checks == () { [] } else { args.checks },
    locales: locales,
    source: if args.source_locale == () { locales[0] } else { args.source_locale },
    gaps_script: if args.gaps_script == () { "" } else { args.gaps_script },
    strict: args.strict_locales == true,
    trailers: if args.commit_trailers == () { "" } else { args.commit_trailers },
    do_commit: args.commit != false,
    do_push: args.push != false,
};

let work = [];
for s in shards {
    if s.exclude == () { s.exclude = []; }
    work.push(#{ shard: s, items: [] });
}

phase("Find");
let find_jobs = [];
for w in work {
    find_jobs.push(#{
        prompt: find_prompt(ctx, w.shard),
        label: "find:" + w.shard.id,
        capability_mode: "read-only",
        output_schema: findings_schema,
    });
}
let find_results = parallel(find_jobs);
let find_i = 0;
let find_total = 0;
for r in find_results {
    let found = [];
    if r != () && r.success { found = take(r.output, "findings"); }
    let kept = filter_to_shard(work[find_i].shard, found);
    work = set_items(work, find_i, kept);
    find_total += kept.len();
    find_i += 1;
}
log(find_total.to_string() + " raw findings across " + work.len().to_string() + " shards");

phase("Verify");
let verify_jobs = [];
let verify_index = [];
let vf_i = 0;
for w in work {
    if w.items.len() > 0 {
        verify_jobs.push(#{
            prompt: verify_prompt(ctx, w.shard, json_encode(w.items)),
            label: "verify:" + w.shard.id,
            capability_mode: "read-only",
            output_schema: confirmed_schema,
        });
        verify_index.push(vf_i);
    }
    vf_i += 1;
}

if verify_jobs.len() > 0 {
    let verify_results = parallel(verify_jobs);
    let vr_i = 0;
    for r in verify_results {
        let si = verify_index[vr_i];
        let confirmed = [];
        if r != () && r.success { confirmed = take(r.output, "confirmed"); }
        work = set_items(work, si, filter_to_shard(work[si].shard, confirmed));
        vr_i += 1;
    }
}

log(item_count(work).to_string() + " findings survived verification");

let changed = [];
let new_keys = [];

phase("Fix");
if item_count(work) > 0 {
    let acc = fix_work(ctx, work, fix_schema, changed, new_keys);
    changed = acc.changed;
    new_keys = acc.new_keys;
}

phase("Review");
let last_fp = "";
for round_i in [1, 2, 3] {
    if item_count(work) == 0 && round_i > 1 { break; }

    let review_jobs = [];
    let review_idx = [];
    let rv_i = 0;
    for w in work {
        let files = [];
        for path in changed {
            if in_shard(w.shard, path) { files = push_unique(files, path); }
        }
        if files.len() > 0 || w.items.len() > 0 {
            review_jobs.push(#{
                prompt: review_prompt(ctx, w.shard, json_encode(files)),
                label: "review" + round_i.to_string() + ":" + w.shard.id,
                capability_mode: "read-only",
                output_schema: review_schema,
            });
            review_idx.push(rv_i);
        }
        rv_i += 1;
    }
    if review_jobs.len() == 0 { break; }

    let review_results = parallel(review_jobs);
    let i = 0;
    for w in work {
        work = set_items(work, i, []);
        i += 1;
    }
    let rr_i = 0;
    let leftover = 0;
    for r in review_results {
        let si = review_idx[rr_i];
        let leftover_items = [];
        if r != () && r.success {
            if r.output == () || r.output.clean != true {
                leftover_items = filter_to_shard(work[si].shard, take(r.output, "remaining"));
            }
        }
        work = set_items(work, si, leftover_items);
        leftover += leftover_items.len();
        rr_i += 1;
    }
    log("review round " + round_i.to_string() + ": " + leftover.to_string() + " remaining");

    let fp = fingerprint(json_encode(items_snapshot(work)));
    if fp == last_fp {
        log("review loop stalled; stopping");
        break;
    }
    last_fp = fp;

    if leftover == 0 { break; }

    let acc = fix_work(ctx, work, fix_schema, changed, new_keys);
    changed = acc.changed;
    new_keys = acc.new_keys;
}

phase("Localize");
if ctx.catalogs.len() > 0 {
    let loc = agent(
        localize_prompt(ctx, new_keys),
        #{
            label: "localize",
            capability_mode: "all",
            output_schema: localize_schema,
        }
    );
    if loc != () && loc.success && loc.output != () {
        for path in take(loc.output, "changed_files") { changed = push_unique(changed, path); }
    }
}

phase("Ship");
if changed.len() == 0 {
    complete(#{ summary: "Copy already meets the bar. Nothing to ship.", changed_files: [], commits: [] });
}

let ship = agent(
    ship_prompt(ctx, changed),
    #{
        label: "ship",
        capability_mode: "all",
        output_schema: ship_schema,
    }
);

let commits = [];
let ship_notes = "";
if ship != () && ship.success && ship.output != () {
    if ship.output.commits != () { commits = ship.output.commits; }
    if ship.output.notes != () { ship_notes = ship.output.notes; }
}

complete(#{
    summary: changed.len().to_string() + " files changed; " + commits.len().to_string() + " commits",
    changed_files: changed,
    new_keys: new_keys,
    commits: commits,
    notes: ship_notes,
});
