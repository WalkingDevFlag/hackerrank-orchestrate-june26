# Multi-Modal Evidence Review — Solution

A lean, **single-call-per-claim** vision pipeline that verifies damage claims
(`car` / `laptop` / `package`) against submitted photos, a chat transcript,
user history, and minimum-evidence requirements — then emits the required
14-column `output.csv`.

## Design in one paragraph

For each claim we make **one** multimodal model call (Anthropic Claude on
**AWS Bedrock**) that receives all the claim's images (each labelled with its
image ID), the customer chat, the matched evidence-requirement text, and a
compact user-history summary. The model returns strict JSON for the 10
model-owned fields. **The model does the visual judgement; deterministic Python
enforces the contract** — legal enum values, the "user history is risk context
only / never overrides clear photo evidence" rule, risk-flag consistency, and
exact column order. This split keeps the system accurate *and* reproducible.

## Layout

```
code/
├── main.py                 # run on dataset/claims.csv -> output.csv
├── requirements.txt
├── evaluation/
│   └── main.py             # score on labeled samples; compare prompt configs
└── orchestrate/
    ├── config.py           # all knobs; secrets via AWS cred chain only
    ├── data.py             # load + join claims / history / evidence rules
    ├── images.py           # decode (incl. WebP-as-jpg), downscale, base64
    ├── prompt.py           # system + user prompt builders (full / lean)
    ├── bedrock_client.py   # Bedrock call + retry + cache + token accounting + mock
    ├── schema.py           # 14-col contract + enum coercion (legal output guaranteed)
    ├── metrics.py          # per-column accuracy, confusion, Jaccard for set fields
    └── pipeline.py         # orchestration + deterministic post-processing
```

## Setup

```bash
pip install -r code/requirements.txt
```

AWS credentials come from the **standard AWS credential chain** (env vars,
`~/.aws/config`, SSO). No API keys are read or stored by this code.

```bash
export AWS_REGION=us-west-2
export BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0  # default
```

## Run

```bash
# Full test run -> ./output.csv
python code/main.py

# Evaluate on the 20 labeled samples (with expected answers)
python code/evaluation/main.py --variant full

# Compare two prompt configurations (full vs lean) for the report
python code/evaluation/main.py --compare --report code/evaluation/evaluation_report.md

# Offline plumbing test — no Bedrock/creds needed (mock model)
ORCH_MOCK=1 python code/main.py --out /tmp/out.csv
```

## Key behaviours

- **Images are the source of truth.** History only adds `risk_flags`; a code
  guard prevents history from inventing or flipping a verdict on its own.
- **Language-agnostic** claim extraction (Hindi/Hinglish/Spanish/Chinese chats
  appear in the data).
- **Prompt-injection safe**: instruction-like text inside an image is ignored
  and flagged `text_instruction_present`.
- **Cost control**: one call per claim; on-disk cache keyed by
  (model, prompt, normalised image bytes) so re-runs and the eval pass don't
  re-pay; exponential-backoff retry for Bedrock throttling; images downscaled
  to 1024px longest edge to cap per-image tokens.
- **Determinism**: temperature 0, fixed prompts, stable column order.

## Configuration (env vars)

| Var | Default | Meaning |
|---|---|---|
| `AWS_REGION` | `us-west-2` | Bedrock region |
| `BEDROCK_MODEL_ID` | Claude Sonnet 4.5 profile | model id / inference profile |
| `ORCH_TEMPERATURE` | `0` | sampling temperature |
| `ORCH_MAX_IMAGE_DIM` | `1024` | longest-edge downscale cap |
| `ORCH_MAX_WORKERS` | `4` | concurrent claims (RPM-friendly) |
| `ORCH_USE_CACHE` | `1` | on-disk response cache |
| `ORCH_MOCK` | `0` | offline mock model (no creds) |
