from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .bedrock_client import BedrockVLM
from .config import SETTINGS
from .data import Claim
from .images import load_claim_images
from .prompt import build_messages
from .schema import (
    MODEL_FIELDS,
    MRR_VISUAL_TRIGGERS,
    OUTPUT_COLUMNS,
    coerce_row,
)


def _derive_history_flags(claim: Claim, claim_status: str, visual_flags: list[str]) -> tuple[bool, bool]:
    hist_flags = (claim.history.get("history_flags", "") or "").lower()
    user_history_risk = "user_history_risk" in hist_flags
    manual_review = (
        user_history_risk
        or "manual_review_required" in hist_flags
        or bool(set(visual_flags) & MRR_VISUAL_TRIGGERS)
    )
    return user_history_risk, manual_review


def post_process(coerced: dict, claim: Claim) -> dict:
    out = dict(coerced)
    visual_flags: list[str] = list(out.pop("visual_flags", []))
    status = out["claim_status"]

    out["evidence_standard_met"] = "false" if status == "not_enough_information" else "true"

    is_identity_pair = ("wrong_object" in visual_flags and len(claim.image_ids) >= 2)
    if status == "not_enough_information":
        out["severity"] = "unknown"
        if not is_identity_pair:
            out["issue_type"] = "unknown"

    if out["issue_type"] == "none":
        out["severity"] = "none"
    if out["severity"] == "none" and status == "contradicted":
        out["issue_type"] = "none"

    if status == "supported" and out["severity"] in {"none", "unknown"}:
        out["severity"] = "medium"

    if "non_original_image" in visual_flags:
        out["valid_image"] = "false"

    if status == "not_enough_information" and not is_identity_pair:
        if out["supporting_image_ids"] != "none" and not is_identity_pair:
            out["supporting_image_ids"] = "none"
    elif status in {"supported", "contradicted"}:
        if out["supporting_image_ids"] == "none" and claim.image_ids:
            out["supporting_image_ids"] = claim.image_ids[0]

    uhr, mrr = _derive_history_flags(claim, status, visual_flags)
    final = list(dict.fromkeys(visual_flags))
    if uhr:
        final.append("user_history_risk")
    if mrr:
        final.append("manual_review_required")
    out["risk_flags"] = ";".join(final) if final else "none"

    return out


def run_claim(claim: Claim, vlm: BedrockVLM, variant: str = "full", fewshot: bool = False) -> dict:
    system, content = build_messages(claim, variant=variant, fewshot=fewshot)
    n_images = len(load_claim_images(claim.image_files))
    raw = vlm.complete_json(system, content, n_images=n_images)
    coerced = coerce_row(raw, claim.claim_object, claim.image_ids)
    final = post_process(coerced, claim)
    return final


def _full_row(claim: Claim, model_out: dict) -> dict:
    return {
        "user_id": claim.user_id,
        "image_paths": claim.image_paths,
        "user_claim": claim.user_claim,
        "claim_object": claim.claim_object,
        **{k: model_out[k] for k in MODEL_FIELDS},
    }


def run_claims(
    claims: list[Claim],
    *,
    variant: str = "full",
    fewshot: bool = False,
    vlm: BedrockVLM | None = None,
    max_workers: int | None = None,
) -> tuple[list[dict], BedrockVLM]:
    vlm = vlm or BedrockVLM()
    workers = max_workers or SETTINGS.max_workers
    results: dict[int, dict] = {}

    def task(i: int, c: Claim):
        return i, _full_row(c, run_claim(c, vlm, variant=variant, fewshot=fewshot))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(task, i, c) for i, c in enumerate(claims)]
        for fut in as_completed(futs):
            i, row = fut.result()
            results[i] = row

    ordered = [results[i] for i in range(len(claims))]
    return ordered, vlm


def write_output(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in OUTPUT_COLUMNS})
