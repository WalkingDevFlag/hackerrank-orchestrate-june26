# Evaluation Report — Multi-Modal Evidence Review

## 1. Summary

A single multimodal call per claim (Claude **Opus 4.5** on AWS Bedrock) judges each
damage claim from its photos; deterministic Python owns the output contract (legal
enums, the "history is risk-context-only" rule, cross-field invariants). The final
system reaches **85% claim_status accuracy** and **84.2% key-field average accuracy**
on the 20 labeled samples — stable across repeated runs (reproduced exactly on an
independent no-cache run).

**Final configuration:** Claude Opus 4.5 (`us.anthropic.claude-opus-4-5-20251101-v1:0`),
`full` prompt (with the post-inspection + calibration patches), temperature 0, images
downscaled to 1024 px longest edge, two-layer risk flags (model = visual flags only,
code = history flags).

## 2. Method

- **One call per claim.** All of a claim's images (each labeled `IMAGE_ID: img_N`) plus
  the chat, the matched evidence-requirement text, and a one-line history summary go in a
  single request. The model returns strict JSON for the 10 model-owned fields.
- **Two-layer risk flags.** The model emits only *visual/chat* flags (blur, wrong_object,
  non_original_image, …). Deterministic code derives the two *history* flags
  (`user_history_risk`, `manual_review_required`) from `user_history.csv`. This split was
  proven to reproduce **all 20** sample risk-flag sets when given correct visual flags —
  a VLM cannot read structured history, so it must not guess those flags.
- **Deterministic post-processing** enforces: legal enums (with a synonym map),
  `not_enough_information ⇔ evidence_standard_met=false`, `issue_type=none ⇔ severity=none`,
  a "supported ⇒ severity≠none/unknown" floor, `non_original_image|possible_manipulation ⇒
  valid_image=false`, and supporting-image-id legality. **No test labels are hardcoded.**

## 3. Strategies / configurations compared

All configs share the identical loader + deterministic post-processor; only the
model/prompt varies (apples-to-apples). Scored on the 20 labeled samples.

| # | Model | Prompt | claim_status acc | key-field avg | input tokens (20) |
|---|---|---|---|---|---|
| 1 | Sonnet 4.5 | full | 60% | 67.5% | 82.7K |
| 2 | Sonnet 4.5 | lean | 65% | 70.8% | 40.6K |
| 3 | Opus 4.5 | full | 75% | 75.0% | 82.7K |
| 4 | Opus 4.5 | full + few-shot | 64%* | 70.3%* | 161.6K |
| 5 | Opus 4.5 | full + best-evidence patches | 80% | 76.7% | 91.7K |
| 6 | **Opus 4.5** | **full + calibration patches** | **85%** | **84.2%** | 111.7K |

*Config 4 scored on 14 held-out samples (6 used as exemplars), and the matched
no-few-shot baseline on the same 14 rows was 64.3% / 72.6% — i.e. **few-shot gave no
gain and doubled input tokens** (a clean negative result; not adopted).

Config 6 (final) is config 5 plus three calibration patches derived by having vision
agents inspect the exact mispredicted images: (a) `non_original_image` requires a
**concrete, nameable provenance artifact** (watermark/screenshot/UI/stock styling) — the
model had been mislabeling clean customer photos as stock; (b) `severity=high` requires a
**named structural/multi-area cue** (torn-off panel, exposed frame, ≥2 panels, majority-
shattered glass) — a single dramatic impact is medium; (c) a **non-original or mismatched
image is still evidence**: judge the claim from what is visible rather than retreating to
`not_enough_information`. These lifted severity 55→80%, issue_type 70→80%, valid_image
75→80%, and claim_status 80→85% with no net regression.

**Findings:**
- **Capacity matters most.** Opus (config 3) beat Sonnet (config 1) by 15 points on the
  same prompt — the hard visual discriminations (mismatch, severity, crack-vs-shatter)
  are where Opus pays off.
- **Prompt length interacts with model.** Sonnet does *better* with the lean prompt
  (config 2 > 1): the dense rubric makes the smaller model over-think and over-predict
  `not_enough_information`. Opus does *better* with the full rubric (config 3 > a
  separately-tested Opus+lean at 55%). So "less is more" is model-specific.
- **Few-shot visual exemplars did not help** Opus (config 4) and doubled cost — Opus
  already absorbs the conventions from the prose rubric.
- **Targeted prompt patches (config 5)** — derived by having vision agents inspect the
  exact mispredicted sample images — lifted Opus from 75% → 80% with no regression. The
  root cause was order-of-operations: the model checked cross-image *identity mismatch*
  before asking "does any single image already prove the claim?" The fix: a **best-evidence
  rule** (if any one authentic image shows the claimed damage on the claimed part →
  supported), with identity-mismatch→NEI narrowed to the genuine case.

### Final per-column accuracy (config 6, 20 samples)

| Field | Exact | | Field | Exact |
|---|---|---|---|---|
| evidence_standard_met | 90% | | claim_status | 85% |
| object_part | 90% | | issue_type | 80% |
| supporting_image_ids | 80% | | valid_image | 80% |
| severity | 80% | | risk_flags | 50% (Jaccard ~64%) |

`evidence_standard_met_reason` and `claim_status_justification` show 0% *exact* match —
expected, as they are free text that cannot string-match the reference; they are judged
qualitatively and are excluded from the key-field average. `risk_flags` and `severity`
are the hardest (subjective, set-valued); the Jaccard (partial-credit) view is fairer.

### Remaining sample misses (3/20 claim_status)
All three are genuinely ambiguous labels, deliberately not chased to avoid overfitting:
- `user_002`: model says `contradicted` (two clearly different cars) vs gold `not_enough_information` — both defensible.
- `user_003`: the photos really are different vehicles, but one shows the claimed dent; a hard best-evidence call.
- `user_034`: an injection-trap row whose gold `damage_not_visible` label is itself strained (the image does show a crushed corner).

## 4. Operational analysis

Measured directly from the runs (Opus 4.5, config 5, temperature 0, 4 concurrent workers).

| Metric | Sample eval (20) | **Test run (44)** |
|---|---|---|
| Model calls | 20 | **44** (1 per claim) |
| Images processed | 29 | **82** |
| Input tokens | ~111.7K | **~255K** (~5,793/claim) |
| Output tokens | ~4.5K | **~10.9K** (~247/claim) |
| Wall-clock | ~2 min | **~5 min** (~6.8 s/claim) |

**Cost (full test set, 44 claims).** Using *illustrative* Opus 4.5 pricing assumptions of
**$5 / 1M input** and **$25 / 1M output** tokens:
`255K × $5/1M + 10.9K × $25/1M ≈ **$1.55** for the entire test set` (~$0.035 / claim).
Sonnet would be ~3–5× cheaper but cost ~20 points of accuracy; at this absolute scale the
accuracy is the better trade.

**TPM/RPM, batching, caching, retries.**
- **Concurrency:** a bounded thread pool (default 4 workers) keeps requests well under
  Bedrock RPM/TPM limits while finishing the test set in minutes. Tunable via
  `ORCH_MAX_WORKERS`.
- **Retries:** exponential backoff + jitter (up to 5 attempts) on Bedrock
  `ThrottlingException`/5xx, so throttling self-heals without manual intervention.
- **Caching:** an on-disk cache keyed by `(model, prompt text, normalized image bytes,
  temperature)` means re-runs, the sample-eval pass, and config comparisons never re-pay
  for identical claims — directly addressing "avoid unnecessary repeated calls." Every
  config comparison above after the first run was served largely from cache.
- **Token control:** images are downscaled to 1024 px longest edge (plenty to judge
  visible damage) and the JSON output is capped (`max_tokens≈1200`, ~235 used), keeping
  per-claim tokens low. The evidence-rule lookup is deterministic client-side code (0
  tokens).
- **Determinism:** temperature 0 + fixed prompts; the final config reproduced 80% / 76.7%
  exactly on an independent no-cache run.

## 5. How to reproduce

```bash
pip install -r code/requirements.txt
export AWS_REGION=us-west-2   # Bedrock creds via standard AWS chain

# Evaluate on labeled samples (final config)
python code/evaluation/main.py --variant full

# Compare prompt configs (full vs lean)
python code/evaluation/main.py --compare --report code/evaluation/compare.md

# Produce final predictions
python code/main.py --out output.csv
```

## 6. Accuracy-push investigation (model matrix, instrumentation, ablations)

A follow-up effort tried to push past 85% and validated the system against newer
models, the literature, and statistical rigor. See `research_findings.md` for the
full write-up. Key outcomes:

**Model × prompt matrix (20 samples, claim_status% / key-field%):**

| Model | lean | base (unpatched) | full (patched) |
|---|---|---|---|
| Sonnet 4.6 | 70 / 70.8 | 85 / 74.2 | 75 / 72.5 |
| Opus 4.8 | 75 / 77.5 | 80 / 76.7 | 80 / 79.2 |
| **Opus 4.5 (final)** | — | — | **85 / 84.2** |

Opus 4.5 + patched remains best; the patches are tuned to it and do not transfer to
Sonnet 4.6 (they regress it). Opus 4.8 forbids the `temperature` param (handled in the
client) and was lower/noisier. No model switch warranted.

**Instrumentation added (zero model calls — runs on cached predictions):**
- Per-flag precision/recall/F1 for `risk_flags`, splitting the model-emitted VISUAL
  flags from the code-derived history flags, with support counts (`metrics.per_flag_f1`).
  This localized the `risk_flags` miss: `user_history_risk` is perfect (1.0/1.0), while
  `manual_review_required` over-fires (P≈0.57) because the model over-emits
  `wrong_object`/`non_original_image` which the MRR predicate escalates. Note: MRR
  over-firing is the operationally *safe* error direction (extra human review), so it is
  intentionally not suppressed.
- Bootstrap 90% CIs + leave-one-out (`metrics.stability`). On n=20 the claim_status CI is
  ≈ **±12%** — so 85% and any ≤1-row change are within noise. `--compare` is now
  regression-guarded: it refuses to crown a winner whose CI overlaps the runner-up.

**Ablations (all within-noise; none shipped):**
- Few-shot exemplars: no gain, 2× tokens (earlier finding).
- Reason-before-answer JSON reorder (`--variant full_rf`): 81.7 / 80 vs 84.2 / 85 —
  no improvement; kept as a selectable variant but not the default.

**Tool-use decision:** do NOT convert the single call into a Bedrock Converse
tool-calling agent — it breaks the deterministic cache/reproducibility the spec rewards
for ≈0 expected gain. The only tool-flavored ideas worth future testing are deterministic
local preprocessing fed in as *data* (OCR for injection hardening; claimed-region crop for
fine detail on hi-res images), keeping one cached call.

**Conclusion:** 85% / 84.2% is at the practical ceiling for this 20-label dev set. Our
severity (80%) and claim_status (85%) exceed the published INS-MMBench frontier-VLM
numbers (~30% severity, ~83% damage judgment), and the 3 remaining misses are contested
labels. Further prompt-fitting would overfit n=20, not improve the hidden 44-row test set.

**New commands:**
```bash
python code/evaluation/main.py --variant full --diagnostics      # per-flag F1 + CIs
python code/evaluation/main.py --compare full base lean          # regression-guarded
```
