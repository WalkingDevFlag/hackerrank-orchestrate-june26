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
