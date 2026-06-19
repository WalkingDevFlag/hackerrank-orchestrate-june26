from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrate.bedrock_client import BedrockVLM
from orchestrate.config import SETTINGS
from orchestrate.data import load_claims
from orchestrate.metrics import format_report, score
from orchestrate.pipeline import run_claims
from orchestrate.schema import MODEL_FIELDS


def evaluate(variant: str, fewshot: bool = False) -> tuple[dict, dict]:
    claims = load_claims(SETTINGS.sample_csv, is_labeled=True)
    vlm = BedrockVLM()
    rows, vlm = run_claims(claims, variant=variant, fewshot=fewshot, vlm=vlm)
    pairs = list(zip(claims, rows))
    if fewshot:
        from orchestrate.fewshot import EXEMPLAR_USER_IDS
        pairs = [(c, r) for c, r in pairs if c.user_id not in EXEMPLAR_USER_IDS]
    predicted = [{k: r[k] for k in MODEL_FIELDS} for _, r in pairs]
    expected = [c.expected for c, _ in pairs]
    result = score(predicted, expected)
    return result, vlm.usage.as_dict()


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate evidence-review on samples")
    ap.add_argument("--variant", choices=["full", "lean"], default="full")
    ap.add_argument("--compare", action="store_true", help="compare full vs lean prompts")
    ap.add_argument("--fewshot", action="store_true", help="prepend few-shot exemplars (scored on held-out samples)")
    ap.add_argument("--report", default="", help="write a markdown report to this path")
    args = ap.parse_args()

    variants = ["full", "lean"] if args.compare else [args.variant]
    sections, summary = [], {}
    for v in variants:
        tag = f"{v}+fewshot" if args.fewshot else v
        print(f"[eval] running variant='{tag}' model={SETTINGS.model_id} mock={SETTINGS.mock}")
        result, usage = evaluate(v, fewshot=args.fewshot)
        summary[tag] = {"key_field_avg_accuracy": result["key_field_avg_accuracy"],
                        "claim_status_accuracy": result["claim_status_accuracy"],
                        "usage": usage}
        sections.append(format_report(result, title=f"Config: prompt='{tag}'"))
        sections.append(f"\nOperational usage for '{tag}': `{json.dumps(usage)}`\n")
        print(json.dumps(summary[tag], indent=2))

    if args.report:
        Path(args.report).write_text("\n\n".join(sections), encoding="utf-8")
        print(f"[done] wrote report -> {args.report}")

    if args.compare:
        best = max(summary, key=lambda v: summary[v]["key_field_avg_accuracy"])
        print(f"[compare] best config by key-field accuracy: '{best}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
