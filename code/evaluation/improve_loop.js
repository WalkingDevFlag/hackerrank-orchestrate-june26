export const meta = {
  name: 'accuracy-hill-climb',
  description: 'Stateful hill-climb: propose a generalizable rule, eval live, strict-gate keep/drop vs incumbent, loop until dry',
  phases: [
    { title: 'Climb', detail: 'propose -> eval -> strict gate (no-regression + >=2 net + critic + fresh confirm) -> keep/revert' },
    { title: 'Report', detail: 'summarize accepted/rejected rules and final score' },
  ],
}

const REPO = '/Volumes/workplace/HackerRank/hackerrank-orchestrate-june26'
const MODEL = 'us.anthropic.claude-opus-4-5-20251101-v1:0'
const RULES_FILE = `${REPO}/code/.cache/candidate_rules.txt`   // injected via ORCH_EXTRA_RULES_FILE
const ACCEPTED_FILE = `${REPO}/code/.cache/accepted_rules.txt` // persists accepted rules across iterations
const CREDS = 'ada credentials update --account=135702137383 --role=IibsAdminAccess-DO-NOT-DELETE --provider=conduit --once'

// args may arrive as an object or a JSON string (or be absent); normalize.
let A = args
if (typeof A === 'string') { try { A = JSON.parse(A) } catch (e) { A = undefined } }
A = A || {}
// Hardcoded incumbent fallback (established 2026-06-19, cached): total_key_correct 101/120.
const DEFAULT_INCUMBENT = {
  variant: 'full', n: 20, claim_status_accuracy: 0.85, key_field_avg_accuracy: 0.842,
  claim_status_ci90: [0.7, 0.95],
  per_field_correct: { claim_status: 17, evidence_standard_met: 19, valid_image: 15,
                       issue_type: 16, object_part: 18, severity: 16 },
  total_key_correct: 101,
}
const incumbent = A.incumbent || DEFAULT_INCUMBENT
const MAX_ITERS = A.maxIters ?? 15
const DRY_STOP = A.dryStop ?? 3
const MIN_NET_GAIN = 2   // must improve total_key_correct by >=2 (beat 1-row noise)

const SHARED = `
You are improving a multi-modal insurance damage-claim adjudicator (Claude Opus on Bedrock).
For each claim, ONE vision call returns 10 fields; deterministic code enforces enums + history flags.
Current best on 20 labeled samples: claim_status ${Math.round(incumbent.claim_status_accuracy*100)}%, total_key_correct ${incumbent.total_key_correct}/120.
Per-field correct (/20): ${JSON.stringify(incumbent.per_field_correct)}.

The system prompt already covers: images-are-truth; history-is-risk-context-only; conservative severity
(medium default, high needs structural cues); crack vs glass_shatter vs broken_part by component state;
non_original_image requires a nameable artifact; best-evidence on multi-image sets; anti-injection.

CRITICAL CONSTRAINT — NO OVERFITTING: there are only 20 labels (1 row = 5%, CI ~+-12%). A rule that names
or targets a specific user_id / case is FORBIDDEN. Propose only GENERAL, transferable rules that would help
the hidden 44-row test set, phrased as principles a reviewer applies to ANY claim.
`

const PROPOSE_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['target_field','rule_text','rationale','is_generalizable'],
  properties: {
    target_field: { type: 'string', description: 'which weak field this most helps (valid_image/severity/issue_type/risk_flags/claim_status)' },
    rule_text: { type: 'string', description: 'the verbatim calibration rule to ADD to the prompt; <=4 sentences; NO case/user_id references' },
    rationale: { type: 'string' },
    is_generalizable: { type: 'boolean', description: 'true only if this is a transferable principle, not row-fitting' },
  },
}

const CRITIC_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['is_generalizable','overfit_risk','verdict','why'],
  properties: {
    is_generalizable: { type: 'boolean' },
    overfit_risk: { type: 'string', description: 'low/medium/high' },
    verdict: { type: 'string', description: 'ACCEPT or REJECT' },
    why: { type: 'string' },
  },
}

phase('Climb')
let acceptedRules = []   // list of {field, rule}
let dryStreak = 0
let cur = incumbent
const history = []

for (let iter = 1; iter <= MAX_ITERS && dryStreak < DRY_STOP; iter++) {
  // 1) PROPOSE a generalizable rule, told the current weak fields + already-accepted rules.
  const weakest = Object.entries(cur.per_field_correct).sort((a,b)=>a[1]-b[1]).slice(0,3)
    .map(([f,c])=>`${f} ${c}/20`).join(', ')
  const proposal = await agent(
    `${SHARED}\n\nIteration ${iter}. Weakest fields right now: ${weakest}.\n` +
    `Rules already ACCEPTED this run (do NOT repeat or contradict):\n${acceptedRules.map(r=>'- '+r.rule).join('\n') || '(none yet)'}\n\n` +
    `Inspect a few sample images if useful (Read ${REPO}/dataset/images/sample/case_XXX/img_N.jpg) to ground your idea. ` +
    `Propose ONE new GENERAL calibration rule (<=4 sentences, no case/user_id references) most likely to fix a weak field on UNSEEN claims. ` +
    `If you cannot think of a genuinely generalizable improvement, set is_generalizable=false.`,
    { label: `propose#${iter}`, phase: 'Climb', schema: PROPOSE_SCHEMA, agentType: 'general-purpose' }
  )
  if (!proposal || !proposal.is_generalizable || !proposal.rule_text?.trim()) {
    dryStreak++; history.push({iter, action:'no-proposal', dryStreak}); log(`iter ${iter}: no generalizable proposal (dry ${dryStreak}/${DRY_STOP})`); continue
  }

  // 2) APPLY: write accepted rules + the candidate to the injected rules file; refresh creds; score live (no cache).
  const candidateBlock = acceptedRules.map(r=>r.rule).concat([proposal.rule_text.trim()]).join('\n')
  const evalCmd =
    `${CREDS} >/dev/null 2>&1; cd ${REPO}; mkdir -p code/.cache; ` +
    `cat > '${RULES_FILE}' <<'RULESEOF'\n${candidateBlock}\nRULESEOF\n` +
    `BEDROCK_MODEL_ID="${MODEL}" ORCH_EXTRA_RULES_FILE='${RULES_FILE}' ORCH_USE_CACHE=0 ` +
    `python3 code/evaluation/score_json.py full 2>/dev/null | grep SCORE_JSON`
  const evalOut = await agent(
    `Run this shell command EXACTLY (it scores a candidate prompt rule live on the 20 samples) and return ONLY the line starting with SCORE_JSON, verbatim:\n\n${evalCmd}`,
    { label: `eval#${iter}:${proposal.target_field}`, phase: 'Climb', agentType: 'general-purpose' }
  )
  let cand = null
  try { cand = JSON.parse((evalOut||'').split('SCORE_JSON ')[1].trim().split('\n')[0]) } catch(e) { cand = null }
  if (!cand || typeof cand.total_key_correct !== 'number') {
    dryStreak++; history.push({iter, action:'eval-failed', rule:proposal.rule_text, dryStreak})
    log(`iter ${iter}: eval failed/unparseable (dry ${dryStreak}/${DRY_STOP})`); continue
  }

  // 3) STRICT GATE.
  const netGain = cand.total_key_correct - cur.total_key_correct
  const regressed = Object.keys(cur.per_field_correct).filter(f => (cand.per_field_correct[f] ?? -1) < cur.per_field_correct[f])
  const passesNumeric = (netGain >= MIN_NET_GAIN) && (regressed.length === 0)
  log(`iter ${iter} [${proposal.target_field}] net=${netGain>=0?'+':''}${netGain} regressions=[${regressed.join(',')||'none'}] ` +
      `(cand ${cand.total_key_correct} vs cur ${cur.total_key_correct})`)

  if (!passesNumeric) {
    dryStreak++; history.push({iter, action:'reject-numeric', netGain, regressed, rule:proposal.rule_text, dryStreak}); continue
  }

  // 4) OVERFIT CRITIC (only for numerically-passing candidates).
  const critic = await agent(
    `${SHARED}\n\nA candidate rule numerically improved the 20-sample score by ${netGain} fields with NO field regressing.\n` +
    `RULE: "${proposal.rule_text}"\nTARGET: ${proposal.target_field}\nRATIONALE: ${proposal.rationale}\n\n` +
    `As a skeptical overfit-critic: is this a GENERAL principle that will transfer to the hidden 44-row test set, or is it fitted to the 20 dev rows? ` +
    `A +${netGain}-field gain on n=20 is within the noise band, so demand a clear mechanistic reason it generalizes. Verdict ACCEPT only if genuinely generalizable and low overfit risk.`,
    { label: `critic#${iter}`, phase: 'Climb', schema: CRITIC_SCHEMA, agentType: 'general-purpose' }
  )
  if (!critic || critic.verdict !== 'ACCEPT' || !critic.is_generalizable) {
    dryStreak++; history.push({iter, action:'reject-critic', netGain, rule:proposal.rule_text, critic:critic?.why, dryStreak})
    log(`iter ${iter}: critic REJECTED (overfit risk ${critic?.overfit_risk||'?'})`); continue
  }

  // 5) FRESH CONFIRM: re-run no-cache to ensure the gain is real, not a fluke.
  const confirmOut = await agent(
    `Run this EXACTLY and return ONLY the SCORE_JSON line:\n\n${evalCmd}`,
    { label: `confirm#${iter}`, phase: 'Climb', agentType: 'general-purpose' }
  )
  let conf = null
  try { conf = JSON.parse((confirmOut||'').split('SCORE_JSON ')[1].trim().split('\n')[0]) } catch(e) { conf = null }
  const confirmedGain = conf ? (conf.total_key_correct - cur.total_key_correct) : -999
  const confirmedRegressions = conf ? Object.keys(cur.per_field_correct).filter(f => (conf.per_field_correct[f] ?? -1) < cur.per_field_correct[f]) : ['eval-failed']
  if (!conf || confirmedGain < MIN_NET_GAIN || confirmedRegressions.length > 0) {
    dryStreak++; history.push({iter, action:'reject-unconfirmed', netGain, confirmedGain, rule:proposal.rule_text, dryStreak})
    log(`iter ${iter}: gain NOT confirmed on rerun (was +${netGain}, rerun +${confirmedGain}) -> reject`); continue
  }

  // ACCEPT.
  acceptedRules.push({ field: proposal.target_field, rule: proposal.rule_text.trim() })
  cur = conf
  dryStreak = 0
  history.push({iter, action:'ACCEPT', netGain: confirmedGain, rule:proposal.rule_text, newTotal: conf.total_key_correct})
  log(`iter ${iter}: ✅ ACCEPTED (+${confirmedGain} fields, new total ${conf.total_key_correct}/120, claim_status ${Math.round(conf.claim_status_accuracy*100)}%)`)
}

// persist accepted rules so the main agent can fold them into the locked prompt if any survived.
phase('Report')
const persistCmd = acceptedRules.length
  ? `mkdir -p ${REPO}/code/.cache; cat > '${ACCEPTED_FILE}' <<'AEOF'\n${acceptedRules.map(r=>r.rule).join('\n')}\nAEOF\necho saved`
  : `echo 'no rules accepted'`
await agent(`Run exactly and return its output: ${persistCmd}`, { label: 'persist', phase: 'Report', agentType: 'general-purpose' })

return {
  incumbent_total: incumbent.total_key_correct,
  final_total: cur.total_key_correct,
  final_claim_status: cur.claim_status_accuracy,
  accepted_count: acceptedRules.length,
  accepted_rules: acceptedRules,
  history,
}
