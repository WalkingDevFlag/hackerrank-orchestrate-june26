from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrate.bedrock_client import BedrockVLM
from orchestrate.config import SETTINGS
from orchestrate.data import load_claims
from orchestrate.metrics import KEY_FIELDS, score, stability
from orchestrate.pipeline import run_claims
from orchestrate.schema import MODEL_FIELDS


def main() -> int:
    variant = sys.argv[1] if len(sys.argv) > 1 else "full"
    claims = load_claims(SETTINGS.sample_csv, is_labeled=True)
    vlm = BedrockVLM()
    rows, vlm = run_claims(claims, variant=variant, vlm=vlm)
    predicted = [{k: r[k] for k in MODEL_FIELDS} for r in rows]
    expected = [c.expected for c in claims]
    res = score(predicted, expected)
    cs = stability(predicted, expected, "claim_status")
    per_field_correct = {}
    for f in KEY_FIELDS:
        per_field_correct[f] = sum(
            int(str(p.get(f, "")).strip().lower() == str(e.get(f, "")).strip().lower())
            for p, e in zip(predicted, expected)
        )
    out = {
        "variant": variant,
        "n": res["n"],
        "claim_status_accuracy": res["claim_status_accuracy"],
        "key_field_avg_accuracy": res["key_field_avg_accuracy"],
        "claim_status_ci90": cs["ci90"],
        "per_field_correct": per_field_correct,
        "total_key_correct": sum(per_field_correct.values()),
        "usage": vlm.usage.as_dict(),
    }
    print("SCORE_JSON " + json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
