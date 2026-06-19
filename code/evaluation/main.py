from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrate.bedrock_client import BedrockVLM
from orchestrate.config import SETTINGS
from orchestrate.data import load_claims
from orchestrate.metrics import (
    bootstrap_ci,
    format_report,
    per_flag_f1,
    score,
    stability,
)
from orchestrate.pipeline import run_claims
from orchestrate.schema import MODEL_FIELDS


def evaluate(variant: str, fewshot: bool = False) -> tuple[dict, dict, list[dict], list[dict]]:
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
    return result, vlm.usage.as_dict(), predicted, expected


def _diagnostics_text(predicted: list[dict], expected: list[dict]) -> str:
    flag_f1 = per_flag_f1(predicted, expected)
    cs = stability(predicted, expected, "claim_status")
    kf_correct = []
    from orchestrate.metrics import KEY_FIELDS
    for p, e in zip(predicted, expected):
        hits = sum(int(str(p.get(f, "")).strip().lower() == str(e.get(f, "")).strip().lower())
                   for f in KEY_FIELDS)
        kf_correct.append(hits / len(KEY_FIELDS))
    kf_ci = bootstrap_ci([round(x) for x in kf_correct]) if False else _mean_ci(kf_correct)

    lines = ["### Diagnostics", "",
             f"claim_status: {cs['accuracy']:.0%}  90% CI [{cs['ci90'][0]:.0%}, {cs['ci90'][1]:.0%}]"
             f"  (±{cs['ci_halfwidth']:.0%}, LOO swing {cs['loo_swing']:.0%})",
             f"key-field avg: {kf_ci['mean']:.1%}  90% CI [{kf_ci['lo']:.0%}, {kf_ci['hi']:.0%}]",
             "",
             "Per-flag P/R/F1 (visual = model-emitted; history = code-derived):",
             "| flag | subset | support | P | R | F1 |", "|---|---|---|---|---|---|"]
    for f, s in sorted(flag_f1.items(), key=lambda kv: (-kv[1]["support"], kv[0])):
        if s["support"] == 0 and s["subset"] == "visual" and f1_is_trivial(s):
            continue
        lines.append(f"| {f} | {s['subset']} | {s['support']} | {s['precision']:.2f} | "
                     f"{s['recall']:.2f} | {s['f1']:.2f} |")
    hist = [s for f, s in flag_f1.items() if s["subset"] == "history"]
    hist_perfect = all(s["precision"] == 1.0 and s["recall"] == 1.0 for s in hist if s["support"] or True)
    lines.append("")
    lines.append(f"History-flag sub-score perfect (code-derived): {hist_perfect}")
    return "\n".join(lines)


def f1_is_trivial(s: dict) -> bool:
    return s["precision"] == 1.0 and s["recall"] == 1.0 and s["support"] == 0


def _mean_ci(vals: list[float], resamples: int = 2000, seed: int = 11) -> dict:
    from orchestrate.metrics import _seeded_indices
    n = len(vals)
    if not n:
        return {"mean": 0.0, "lo": 0.0, "hi": 0.0}
    means = []
    for r in range(resamples):
        idx = _seeded_indices(n, n, seed + r)
        means.append(sum(vals[i] for i in idx) / n)
    means.sort()
    return {"mean": round(sum(vals) / n, 3),
            "lo": round(means[int(0.05 * resamples)], 3),
            "hi": round(means[int(0.95 * resamples)], 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate evidence-review on samples")
    ap.add_argument("--variant", choices=["full", "full_rf", "base", "lean"], default="full")
    ap.add_argument("--compare", nargs="*", metavar="VARIANT",
                    help="compare variants (default: full base lean); regression-guarded by CI")
    ap.add_argument("--fewshot", action="store_true", help="prepend few-shot exemplars (held-out scoring)")
    ap.add_argument("--diagnostics", action="store_true", help="print per-flag F1 + bootstrap CIs")
    ap.add_argument("--report", default="", help="write a markdown report to this path")
    args = ap.parse_args()

    if args.compare is not None:
        variants = args.compare or ["full", "base", "lean"]
    else:
        variants = [args.variant]

    sections, summary, preds = [], {}, {}
    for v in variants:
        tag = f"{v}+fewshot" if args.fewshot else v
        print(f"[eval] running variant='{tag}' model={SETTINGS.model_id} mock={SETTINGS.mock}")
        result, usage, predicted, expected = evaluate(v, fewshot=args.fewshot)
        cs = stability(predicted, expected, "claim_status")
        summary[tag] = {"key_field_avg_accuracy": result["key_field_avg_accuracy"],
                        "claim_status_accuracy": result["claim_status_accuracy"],
                        "claim_status_ci90": cs["ci90"], "usage": usage}
        preds[tag] = (predicted, expected)
        sections.append(format_report(result, title=f"Config: prompt='{tag}'"))
        if args.diagnostics or args.compare is not None:
            sections.append(_diagnostics_text(predicted, expected))
        sections.append(f"\nOperational usage for '{tag}': `{json.dumps(usage)}`\n")
        print(json.dumps(summary[tag], indent=2))
        if args.diagnostics:
            print(_diagnostics_text(predicted, expected))

    if args.report:
        Path(args.report).write_text("\n\n".join(sections), encoding="utf-8")
        print(f"[done] wrote report -> {args.report}")

    if args.compare is not None and len(variants) > 1:
        ranked = sorted(summary.items(), key=lambda kv: -kv[1]["key_field_avg_accuracy"])
        best_tag, best = ranked[0]
        runner_tag, runner = ranked[1]
        best_lo = best["claim_status_ci90"][0]
        runner_hi = runner["claim_status_ci90"][1]
        if best_lo <= runner_hi:
            print(f"[compare] top='{best_tag}' ({best['key_field_avg_accuracy']:.0%}) but its "
                  f"claim_status CI overlaps '{runner_tag}' — WITHIN NOISE, no clear winner "
                  f"(n={len(preds[best_tag][0])}; 1 row ≈ {100/len(preds[best_tag][0]):.0f}%).")
        else:
            print(f"[compare] clear winner: '{best_tag}' (CI-separated from runner-up).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
