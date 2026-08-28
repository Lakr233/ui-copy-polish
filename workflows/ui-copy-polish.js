// Claude Code Workflow engine for ui-copy-polish.
// Launch: Workflow({ scriptPath: "<SKILL_DIR>/workflows/ui-copy-polish.js", args: <discover JSON + paths + flags> })
// One chain per shard (find → verify → fix → review/fix loop), then localize, then ship.
export const meta = {
  name: 'ui-copy-polish',
  description: 'Polish user-facing UI copy: find, verify, fix, review loop, localize, commit, push',
  whenToUse: 'When the user wants to polish UI copy or runs /ui-copy-polish',
  phases: [
    { title: 'Find', detail: 'scan each shard for UI copy that fails the bar' },
    { title: 'Verify', detail: 'independently confirm each finding' },
    { title: 'Fix', detail: 'apply confirmed rewrites' },
    { title: 'Review', detail: 'review edits and loop until clean (max 3 rounds)' },
    { title: 'Localize', detail: 'complete every locale in every catalog' },
    { title: 'Ship', detail: 'cheap checks, commit by pathspec, push' },
  ],
}

const FINDING = {
  type: 'object',
  required: ['file', 'line', 'current', 'reason', 'text', 'translations'],
  properties: {
    file: { type: 'string' },
    line: { type: 'integer' },
    current: { type: 'string' },
    reason: { type: 'string' },
    text: { type: 'string' },
    translations: { type: 'object', additionalProperties: { type: 'string' } },
    kind: { type: 'string' },
  },
}
const FINDINGS_SCHEMA = { type: 'object', required: ['findings'], properties: { findings: { type: 'array', maxItems: 20, items: FINDING } } }
const CONFIRMED_SCHEMA = { type: 'object', required: ['confirmed'], properties: { confirmed: { type: 'array', maxItems: 20, items: FINDING } } }
const FIX_SCHEMA = {
  type: 'object',
  required: ['changed_files', 'applied'],
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    applied: { type: 'integer' },
    skipped: { type: 'integer' },
    new_keys: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
}
const REVIEW_SCHEMA = { type: 'object', required: ['clean', 'remaining'], properties: { clean: { type: 'boolean' }, remaining: { type: 'array', maxItems: 20, items: FINDING } } }
const LOCALIZE_SCHEMA = { type: 'object', required: ['changed_files', 'filled'], properties: { changed_files: { type: 'array', items: { type: 'string' } }, filled: { type: 'integer' }, notes: { type: 'string' } } }
const SHIP_SCHEMA = {
  type: 'object',
  required: ['commits'],
  properties: {
    commits: {
      type: 'array',
      items: {
        type: 'object',
        required: ['root', 'sha', 'pushed'],
        properties: { root: { type: 'string' }, sha: { type: 'string' }, files: { type: 'array', items: { type: 'string' } }, pushed: { type: 'boolean' } },
      },
    },
    notes: { type: 'string' },
  },
}

if (!args || !args.copy_bar_path || !args.roles_path || !Array.isArray(args.shards)) {
  throw new Error('Pass the JSON from scripts/discover-copy-shards.py plus copy_bar_path, roles_path, gaps_script.')
}

const copyBar = args.copy_bar_path
const roles = args.roles_path
const catalogs = args.catalogs || []
const gitRoots = args.git_roots || []
const locales = args.locales && args.locales.length ? args.locales : ['en']
const source = args.source_locale || locales[0]
const gapsScript = args.gaps_script || ''
const strict = args.strict_locales === true
const checks = args.checks || []
const doCommit = args.commit !== false
const doPush = args.push !== false
const trailers = args.commit_trailers || ''
const maxRounds = args.max_review_rounds || 3
const readOnlyAgent = args.read_only_agent_type || 'Explore'

function hasPrefix(file, prefix) {
  if (!file || !prefix) return false
  if (file === prefix) return true
  return file.startsWith(prefix.replace(/\/+$/, '') + '/')
}
const shards = args.shards.map(s => ({ ...s, exclude: s.exclude || [] }))
if (!shards.length) return { summary: 'No copy shards discovered.', changed_files: [], commits: [] }

function inShard(shard, file) {
  if (!hasPrefix(file, shard.root)) return false
  if (shard.exclude.some(p => hasPrefix(file, p))) return false
  if (!shard.paths.length) return true
  return shard.paths.some(p => hasPrefix(file, p))
}
function filterToShard(shard, items) {
  const all = items || []
  const kept = all.filter(f => f && f.file && inShard(shard, f.file))
  if (all.length - kept.length > 0) log(`dropped ${all.length - kept.length} out-of-shard items from ${shard.id}`)
  return kept
}
function bullets(items) { return (items || []).map(p => `- ${p}`).join('\n') }
function uniq(arr) { return Array.from(new Set((arr || []).filter(Boolean))) }

function intro(section) {
  return `This is a cold start. Read files and grep with your tools. Do not answer from memory.\nRead and obey:\n- ${copyBar}\n- ${roles} (section ${section})\nIf you cannot read those files, return an empty result.\nSOURCE: ${source}\nLOCALES: ${JSON.stringify(locales)}\n`
}
function scopeLines(shard, verb) {
  let p = `\nSHARD: ${shard.id}\nROOT: ${shard.root}\nDEST: ${shard.dest}\n${verb} only these paths (recursive for directories). Do not go outside them:\n${bullets(shard.paths)}`
  if (shard.exclude.length) p += `\nEXCLUDE — another shard owns these subpaths; skip them completely:\n${bullets(shard.exclude)}`
  return p
}
const findPrompt = s => intro('Finder') + scopeLines(s, 'Scan') + `\n\nReturn at most 20 findings, worst first. An empty list is valid only after you grepped these paths for user-facing strings.`
const verifyPrompt = (s, items) => intro('Verifier') + `\nSHARD: ${s.id}\nDEST: ${s.dest}\nIndependently verify these findings. Open each file. Keep only items that are user-visible, fail the bar, and keep meaning and tokens.\nJSON:\n${JSON.stringify(items)}`
function fixPrompt(s, items) {
  let p = intro('Fixer') + scopeLines(s, 'Edit')
  if (s.dest !== 'catalog') p += `\nDo NOT edit localization catalogs in this step — the localizer runs afterwards. Report new source-locale keys in new_keys.`
  return p + `\nApply only these confirmed findings.\nJSON:\n${JSON.stringify(items)}`
}
const reviewPrompt = (s, files) => intro('Reviewer') + `\nSHARD: ${s.id}\nDEST: ${s.dest}\nReview the edited files (read them and git diff them). Return remaining issues that still fail the bar. Do not restyle copy that now passes.\nFILES:\n${JSON.stringify(files)}`

const chains = await pipeline(
  shards,
  s => agent(findPrompt(s), { label: `find:${s.id}`, phase: 'Find', schema: FINDINGS_SCHEMA, agentType: readOnlyAgent })
    .then(r => filterToShard(s, r && r.findings)),
  (found, s) => {
    if (!found.length) return []
    return agent(verifyPrompt(s, found), { label: `verify:${s.id}`, phase: 'Verify', schema: CONFIRMED_SCHEMA, agentType: readOnlyAgent })
      .then(r => filterToShard(s, r && r.confirmed))
  },
  async (confirmed, s) => {
    const state = { id: s.id, dest: s.dest, confirmed: confirmed.length, applied: 0, rounds: 0, clean: true, changed: [], newKeys: [], notes: [] }
    if (!confirmed.length) return state
    log(`${s.id}: ${confirmed.length} confirmed`)
    let batch = confirmed
    let lastFp = ''
    for (let round = 1; round <= maxRounds; round++) {
      const fix = await agent(fixPrompt(s, batch), { label: `fix${round}:${s.id}`, phase: 'Fix', schema: FIX_SCHEMA })
      if (fix) {
        state.changed = uniq(state.changed.concat(fix.changed_files || []))
        state.newKeys = uniq(state.newKeys.concat(fix.new_keys || []))
        state.applied += fix.applied || 0
        if (fix.notes) state.notes.push(fix.notes)
      }
      const files = state.changed.filter(f => inShard(s, f))
      if (!files.length) { state.clean = false; break }
      const rev = await agent(reviewPrompt(s, files), { label: `review${round}:${s.id}`, phase: 'Review', schema: REVIEW_SCHEMA, agentType: readOnlyAgent })
      state.rounds = round
      const remaining = rev && rev.clean !== true ? filterToShard(s, rev.remaining) : []
      log(`${s.id}: review round ${round}, ${remaining.length} remaining`)
      if (!remaining.length) { state.clean = true; break }
      state.clean = false
      const fp = JSON.stringify(remaining)
      if (fp === lastFp) { log(`${s.id}: review loop stalled`); break }
      lastFp = fp
      batch = remaining
    }
    return state
  },
)

const states = chains.filter(Boolean)
let changed = uniq(states.flatMap(st => st.changed))
const newKeys = uniq(states.flatMap(st => st.newKeys))
const applied = states.reduce((n, st) => n + st.applied, 0)
log(`${applied} rewrites applied in ${states.filter(st => st.applied > 0).length} shards; ${newKeys.length} new keys`)

const gapsCmd = gapsScript && catalogs.length
  ? `python3 ${JSON.stringify(gapsScript)} --locales ${locales.join(',')} --source ${source}${strict ? ' --strict' : ''} ${catalogs.map(c => JSON.stringify(c)).join(' ')}`
  : ''
const localeRule = strict
  ? `Every catalog must carry every locale in LOCALES.`
  : `Each catalog completes the locales it already ships (its locales_required in the report). Do not add a locale to a catalog that does not have it.`

phase('Localize')
let localized = null
if (catalogs.length) {
  const p = intro('Localizer')
    + `\nCATALOGS:\n${bullets(catalogs)}\nNEW KEYS FROM THIS RUN:\n${bullets(newKeys)}`
    + (gapsCmd ? `\nRun this first, then fill every gap it lists, then run it again and report the result:\n${gapsCmd}` : '')
    + `\n${localeRule}\nAlso grep the sources under ${JSON.stringify(gitRoots)} for lookup keys missing from the catalogs and add them. Delete an empty-string "" key. Keep each file's existing formatting; no unrelated churn.`
  localized = await agent(p, { label: 'localize', phase: 'Localize', schema: LOCALIZE_SCHEMA })
  if (localized) changed = uniq(changed.concat(localized.changed_files || []))
}

phase('Ship')
if (!changed.length) {
  return { summary: 'Copy already meets the bar. Nothing to ship.', changed_files: [], commits: [], states }
}
const checkLines = checks.map(c => `- ${c.root}\n  stack: ${(c.stack || []).join(', ') || 'unknown'}\n  commands: ${(c.commands || []).length ? c.commands.join(' && ') : '(none)'}\n  notes: ${(c.notes || []).join(' ') || '-'}`).join('\n')
const gapsLine = gapsCmd ? `\nCATALOG CHECK (must report zero errors):\n${gapsCmd}` : ''
const shipPrompt = `This is a cold start. Use tools. Do not answer from memory.\nRead and obey the Shipper section of:\n${roles}\nGIT ROOTS:\n${bullets(gitRoots)}\nCHECKS:\n${checkLines || '(none listed)'}${gapsLine}\nCHANGED FILES FROM THIS RUN:\n${bullets(changed)}\nCOMMIT: ${doCommit}\nPUSH: ${doPush}`
  + (trailers ? `\nAppend these trailer lines to the commit message:\n${trailers}` : '')
  + `\nCommit only the intersection of CHANGED FILES and git status --porcelain. Other dirty files belong to someone else — leave them unstaged and untouched. Never git add -A / -u / . and never commit -a. Never force-push.`
const ship = await agent(shipPrompt, { label: 'ship', phase: 'Ship', schema: SHIP_SCHEMA })

return {
  summary: `${changed.length} files changed; ${ship && ship.commits ? ship.commits.length : 0} commits`,
  changed_files: changed,
  new_keys: newKeys,
  localized,
  commits: ship ? ship.commits : [],
  notes: ship ? ship.notes : 'ship agent returned nothing',
  states,
}
