from __future__ import annotations

from collections import Counter, defaultdict

from .schema import MODEL_FIELDS

SET_FIELDS = {"risk_flags", "supporting_image_ids"}
KEY_FIELDS = ["claim_status", "evidence_standard_met", "valid_image", "issue_type",
              "object_part", "severity"]


def _as_set(v: str) -> set[str]:
    if v is None:
        return set()
    return {t.strip() for t in str(v).replace(",", ";").split(";") if t.strip() and t.strip() != "none"}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score(predicted: list[dict], expected: list[dict]) -> dict:
    assert len(predicted) == len(expected), "row count mismatch"
    n = len(predicted)
    exact = defaultdict(int)
    jacc_sum = defaultdict(float)
    confusion: Counter = Counter()
    per_row = []

    for pred, exp in zip(predicted, expected):
        row_detail = {}
        for f in MODEL_FIELDS:
            pv = str(pred.get(f, "")).strip().lower()
            ev = str(exp.get(f, "")).strip().lower()
            if f in SET_FIELDS:
                j = _jaccard(_as_set(pv), _as_set(ev))
                jacc_sum[f] += j
                row_detail[f] = round(j, 2)
                if j == 1.0:
                    exact[f] += 1
            else:
                match = pv == ev
                exact[f] += int(match)
                row_detail[f] = match
                if f == "claim_status":
                    confusion[(ev, pv)] += 1
        per_row.append(row_detail)

    col_acc = {f: round(exact[f] / n, 3) for f in MODEL_FIELDS}
    set_score = {f: round(jacc_sum[f] / n, 3) for f in SET_FIELDS}
    key_avg = round(sum(col_acc[f] for f in KEY_FIELDS) / len(KEY_FIELDS), 3)

    return {
        "n": n,
        "column_exact_accuracy": col_acc,
        "set_field_jaccard": set_score,
        "key_field_avg_accuracy": key_avg,
        "claim_status_accuracy": col_acc["claim_status"],
        "claim_status_confusion": {f"{k[0]}->{k[1]}": v for k, v in sorted(confusion.items())},
        "per_row": per_row,
    }


VISUAL_FLAGS = {
    "blurry_image", "cropped_or_obstructed", "low_light_or_glare", "wrong_angle",
    "wrong_object", "wrong_object_part", "damage_not_visible", "claim_mismatch",
    "possible_manipulation", "non_original_image", "text_instruction_present",
}
HISTORY_FLAGS = {"user_history_risk", "manual_review_required"}


def per_flag_f1(predicted: list[dict], expected: list[dict]) -> dict:
    flags = sorted(VISUAL_FLAGS | HISTORY_FLAGS)
    stats = {f: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for f in flags}
    for pred, exp in zip(predicted, expected):
        pset = _as_set(str(pred.get("risk_flags", "")).lower())
        eset = _as_set(str(exp.get("risk_flags", "")).lower())
        for f in flags:
            in_p, in_e = f in pset, f in eset
            if in_e:
                stats[f]["support"] += 1
            if in_p and in_e:
                stats[f]["tp"] += 1
            elif in_p and not in_e:
                stats[f]["fp"] += 1
            elif in_e and not in_p:
                stats[f]["fn"] += 1
    out = {}
    for f, s in stats.items():
        tp, fp, fn = s["tp"], s["fp"], s["fn"]
        prec = tp / (tp + fp) if (tp + fp) else (1.0 if s["support"] == 0 else 0.0)
        rec = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        out[f] = {"precision": round(prec, 3), "recall": round(rec, 3),
                  "f1": round(f1, 3), "support": s["support"],
                  "subset": "history" if f in HISTORY_FLAGS else "visual"}
    return out


def _seeded_indices(n: int, draws: int, seed: int) -> list[int]:
    out, x = [], (seed * 1103515245 + 12345) & 0x7FFFFFFF
    for _ in range(draws):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out.append(x % n)
    return out


def bootstrap_ci(per_row_correct: list[int], resamples: int = 2000, seed: int = 7) -> dict:
    n = len(per_row_correct)
    if n == 0:
        return {"mean": 0.0, "lo": 0.0, "hi": 0.0}
    means = []
    for r in range(resamples):
        idx = _seeded_indices(n, n, seed + r)
        means.append(sum(per_row_correct[i] for i in idx) / n)
    means.sort()
    lo = means[int(0.05 * resamples)]
    hi = means[int(0.95 * resamples)]
    return {"mean": round(sum(per_row_correct) / n, 3), "lo": round(lo, 3), "hi": round(hi, 3)}


def stability(predicted: list[dict], expected: list[dict], field: str = "claim_status") -> dict:
    correct = [int(str(p.get(field, "")).strip().lower() == str(e.get(field, "")).strip().lower())
               for p, e in zip(predicted, expected)]
    ci = bootstrap_ci(correct)
    n = len(correct)
    base = sum(correct) / n if n else 0.0
    loo = [round((sum(correct) - correct[i]) / (n - 1), 3) for i in range(n)] if n > 1 else []
    swing = round(max(loo) - min(loo), 3) if loo else 0.0
    return {"field": field, "accuracy": round(base, 3), "ci90": [ci["lo"], ci["hi"]],
            "ci_halfwidth": round((ci["hi"] - ci["lo"]) / 2, 3), "loo_swing": swing}


def format_report(result: dict, title: str = "Sample evaluation") -> str:
    lines = [f"### {title}", "", f"- Rows scored: **{result['n']}**",
             f"- claim_status accuracy: **{result['claim_status_accuracy']:.0%}**",
             f"- key-field avg accuracy: **{result['key_field_avg_accuracy']:.0%}**", "",
             "| Field | Exact accuracy |", "|---|---|"]
    for f, a in result["column_exact_accuracy"].items():
        lines.append(f"| {f} | {a:.0%} |")
    lines.append("")
    lines.append("Set fields (Jaccard overlap): " +
                 ", ".join(f"{f}={v:.0%}" for f, v in result["set_field_jaccard"].items()))
    lines.append("")
    lines.append("claim_status confusion (expected->predicted): " +
                 (", ".join(f"{k}: {v}" for k, v in result["claim_status_confusion"].items()) or "n/a"))
    return "\n".join(lines)
