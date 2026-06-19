# Accuracy Research & Improvement Findings

Synthesis of (1) a 2-model × 3-prompt accuracy matrix, (2) web research on VLM
claim-review architectures, and (3) a multi-agent improvement debate. Answers the
five questions raised during development.

## Q1 — Model × prompt matrix (Opus 4.8 & Sonnet 4.6, lean/base/full), 20 samples

| Model | lean | base (unpatched full) | full (patched) |
|---|---|---|---|
| Sonnet 4.6 | 70% / 70.8% | **85%** / 74.2% | 75% / 72.5% |
| Opus 4.8 | 75% / 77.5% | 80% / 76.7% | 80% / 79.2% |
| **Opus 4.5 (incumbent)** | — | — | **85% / 84.2%** |

*(claim_status% / key-field-avg%. Stability-rechecked fresh: Opus 4.5+patched =
85/84.2 reproducible; Sonnet 4.6+base = 85/75 reproducible; Opus 4.8+full = noisier.)*

**Conclusion:** the incumbent **Opus 4.5 + patched prompt stays best.** Sonnet 4.6
ties on the headline verdict but loses ~10 pts on the other fields; Opus 4.8 is lower
and noisier. The patches were tuned on Opus 4.5 and do **not** transfer to Sonnet 4.6
(they *hurt* it: 85→75). No model switch warranted.

## Q2 — Are there 31 samples?

No. The labeled sample set is **20 rows** (verified against the CSV, the 20 case
folders on disk, and the GitHub source of truth). "31" was the count of **multi-image
rows in the 44-row _test_ set**. We evaluate all 20 sample cases every run.

## Q3 — Should we give the vision model tools? Which?

**Mostly NO.** Do **not** turn the single multimodal call into a Bedrock Converse
agentic tool-calling loop: it breaks the content-hash cache, breaks
determinism/reproducibility (a spec requirement), multiplies calls, and adds
tool-error/anchoring failure modes — for ≈0 expected gain on 20 rows. Also skip
reverse-image-search / SynthID / C2PA / trained forgery detectors (external deps,
spoofable signals, untunable on 20 labels).

**The only tool-flavored ideas worth testing** are deterministic local CPU
preprocessing whose output is injected as quoted, untrusted DATA in the *same* single
call: (a) an OCR pass to surface in-image instruction text for quarantine (injection
hardening + audit, not dev-score), and (b) a deterministic claimed-region crop as a
second non-authoritative image block for fine-detail severity/part on the few hi-res
images (Zoom-Refine / V*/SEAL show magnified crops help fine detail). Both keep one
cached deterministic call.

## Q4 — How to improve accuracy without regression (prioritized roadmap)

**DO NOW (free, zero model calls, zero prediction risk — instrumentation):**
1. **Per-flag P/R/F1 for risk_flags** (split VISUAL subset vs code-derived history
   flags, with support counts). Localizes the ~50% risk_flags miss; confirms the
   history half is already 100%.
2. **Bootstrap CIs + leave-one-out** on the 20-sample score, and make `--compare`
   refuse to crown a winner whose CI overlaps the incumbent ("within noise — no winner").

**A/B BEHIND THE VARIANT FLAG (free, single-call, literature-backed):**
3. **Reason-before-answer JSON reordering** — emit the free-text reasoning fields
   before the enums/flags; bump `max_tokens` to ~1400. ("Let Me Speak Freely?",
   EMNLP 2024: key-ordering + reasoning/format decoupling mitigate JSON's reasoning hit.)
4. **Per-IMAGE_ID describe-then-judge observations block** before verdicts
   (compositional CoT, arXiv:2311.17076) — carry the parsimony clause so it doesn't
   become flag-eager.
5. **Per-flag yes/no checklist for risk_flags** (dichotomic, arXiv:2511.03830) —
   the only field genuinely below par; wash in-distribution, big lift OOD (our regime).
   Default-false + named-reason guardrail; ship only on ≥2-row / clear-Jaccard gain.

**WORTH TESTING (test-set robustness, low dev signal):** deterministic claimed-region
crop (#6 above); OCR-as-data injection hardening.

## Q5 — Web research: similar architectures & validated techniques

- **Our field-difficulty ordering matches the literature exactly.** INS-MMBench
  (arXiv:2406.09105, ICCV 2025): frontier VLMs hit ~83% damage judgment but only
  **~30% severity** and ~62% eligibility. Our severity 80% / claim_status 85% are
  **strong relative to this benchmark** — the remaining misses are task difficulty,
  not bugs. The dominant error class is "reasoning/judgment, not perception," which
  supports our read that user_002/003/034 are ambiguous labels.
- **Production systems keep the LLM out of the decision and put rules in
  deterministic code** (artemxdata/Car-Damage-Assessment-AI; MMLM-CA) — exactly our
  two-layer design (model = visual evidence, code = history flags + invariants). A
  near-identical 5-agent solution to this very challenge exists
  (Samm-05/multimodal-claim-verification-system) but is multi-call with no shown win
  over a single call.
- **Set-valued output (risk_flags) is a known LLM weakness** — autoregressive models
  suppress all-but-one label (arXiv:2505.17510); dichotomic per-label prompting helps
  OOD (arXiv:2511.03830). This is why risk_flags is our hardest field.
- **Self-consistency voting is a no-op here**: at temperature 0 (and Opus 4.8 omits
  temperature entirely) K samples are identical. Raising temperature breaks
  determinism + the cache. Skip.
- **In-image prompt injection defense is "spotlighting" / treat-image-text-as-data**
  (Microsoft arXiv:2403.14720; Simon Willison 2023) — only partly effective, which
  matches our single injection-trap miss (user_034).

Sources fetched include: arXiv 2404.09690, 2406.09105, 2408.02442, 2505.17510,
2511.03830, 2312.14135 (V*/SEAL), 2406.09403 (Visual Sketchpad), 2403.14720
(Spotlighting), OWASP LLM01:2025.

## Overfitting warning (governs every decision)

n=20 ⇒ 1 row = 5%, and a 90% bootstrap CI on the headline numbers is ≈ **±12-15
points**. The current 85/84 and any ≤1-row delta are statistically indistinguishable
from noise. Therefore: never tune wording/crops/thresholds to flip a named row;
instrument before optimizing; accept a change only if a field improves with **no**
field regressing **and** it clears the CI / a ≥2-row bar. The real generalization
target is the 44-row test set (more multi-image & hi-res than dev), so prefer
structurally-general changes over dev-score chasing.
