from __future__ import annotations

from typing import Any

OUTPUT_COLUMNS: list[str] = [
    "user_id",
    "image_paths",
    "user_claim",
    "claim_object",
    "evidence_standard_met",
    "evidence_standard_met_reason",
    "risk_flags",
    "issue_type",
    "object_part",
    "claim_status",
    "claim_status_justification",
    "supporting_image_ids",
    "valid_image",
    "severity",
]

MODEL_FIELDS: list[str] = [
    "evidence_standard_met",
    "evidence_standard_met_reason",
    "risk_flags",
    "issue_type",
    "object_part",
    "claim_status",
    "claim_status_justification",
    "supporting_image_ids",
    "valid_image",
    "severity",
]

CLAIM_STATUS = {"supported", "contradicted", "not_enough_information"}

ISSUE_TYPE = {
    "dent", "scratch", "crack", "glass_shatter", "broken_part", "missing_part",
    "torn_packaging", "crushed_packaging", "water_damage", "stain", "none", "unknown",
}

OBJECT_PART = {
    "car": {
        "front_bumper", "rear_bumper", "door", "hood", "windshield", "side_mirror",
        "headlight", "taillight", "fender", "quarter_panel", "body", "unknown",
    },
    "laptop": {
        "screen", "keyboard", "trackpad", "hinge", "lid", "corner", "port", "base",
        "body", "unknown",
    },
    "package": {
        "box", "package_corner", "package_side", "seal", "label", "contents", "item",
        "unknown",
    },
}

SEVERITY = {"none", "low", "medium", "high", "unknown"}

RISK_FLAGS = {
    "none", "blurry_image", "cropped_or_obstructed", "low_light_or_glare",
    "wrong_angle", "wrong_object", "wrong_object_part", "damage_not_visible",
    "claim_mismatch", "possible_manipulation", "non_original_image",
    "text_instruction_present", "user_history_risk", "manual_review_required",
}

VISUAL_RISK_FLAGS = {
    "blurry_image", "cropped_or_obstructed", "low_light_or_glare", "wrong_angle",
    "wrong_object", "wrong_object_part", "damage_not_visible", "claim_mismatch",
    "possible_manipulation", "non_original_image", "text_instruction_present",
}

MRR_VISUAL_TRIGGERS = {"non_original_image", "possible_manipulation", "wrong_object"}

ISSUE_SYNONYMS = {
    "broken": "broken_part", "shattered": "glass_shatter",
    "shattered_glass": "glass_shatter", "glass_shattered": "glass_shatter",
    "crushed": "crushed_packaging", "torn": "torn_packaging",
    "missing": "missing_part", "water": "water_damage", "liquid_damage": "water_damage",
}
FLAG_SYNONYMS = {
    "watermark": "non_original_image", "watermarked": "non_original_image",
    "stock_image": "non_original_image", "stock": "non_original_image",
    "screenshot": "non_original_image", "manipulated": "possible_manipulation",
    "tampered": "possible_manipulation", "blurry": "blurry_image",
    "obstructed": "cropped_or_obstructed", "cropped": "cropped_or_obstructed",
    "glare": "low_light_or_glare", "low_light": "low_light_or_glare",
    "instruction_text": "text_instruction_present",
}


def _norm(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "_") if value is not None else ""


def _coerce_bool(value: Any, default: str = "false") -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    s = _norm(value)
    if s in {"true", "yes", "1", "t"}:
        return "true"
    if s in {"false", "no", "0", "f"}:
        return "false"
    return default


def _coerce_enum(value: Any, allowed: set[str], default: str) -> str:
    s = _norm(value)
    if s in allowed:
        return s
    if default == "unknown" and s in {"", "n/a", "na", "null", "none_"}:
        return default
    return default


def coerce_visual_flags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        tokens = [_norm(v) for v in value]
    else:
        tokens = [_norm(t) for t in str(value).replace(",", ";").split(";")]
    out: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        t = FLAG_SYNONYMS.get(t, t)
        if t in VISUAL_RISK_FLAGS and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def coerce_supporting_ids(value: Any, available_ids: list[str]) -> str:
    if value is None:
        return "none"
    if isinstance(value, (list, tuple)):
        tokens = [str(v).strip() for v in value]
    else:
        tokens = [t.strip() for t in str(value).replace(",", ";").split(";")]
    avail = set(available_ids)
    kept = [t for t in tokens if t in avail]
    seen: set[str] = set()
    ordered = [t for t in kept if not (t in seen or seen.add(t))]
    return ";".join(ordered) if ordered else "none"


def _coerce_issue(value: Any) -> str:
    s = _norm(value)
    s = ISSUE_SYNONYMS.get(s, s)
    return s if s in ISSUE_TYPE else "unknown"


def coerce_row(model_out: dict, claim_object: str, available_ids: list[str]) -> dict:
    part_set = OBJECT_PART.get(claim_object, {"unknown"})
    raw_flags = model_out.get("visual_risk_flags", model_out.get("risk_flags"))
    out = {
        "evidence_standard_met": _coerce_bool(model_out.get("evidence_standard_met"), "false"),
        "evidence_standard_met_reason": str(model_out.get("evidence_standard_met_reason", "")).strip()
        or "No reason provided.",
        "visual_flags": coerce_visual_flags(raw_flags),
        "issue_type": _coerce_issue(model_out.get("issue_type")),
        "object_part": _coerce_enum(model_out.get("object_part"), part_set, "unknown"),
        "claim_status": _coerce_enum(model_out.get("claim_status"), CLAIM_STATUS, "not_enough_information"),
        "claim_status_justification": str(model_out.get("claim_status_justification", "")).strip()
        or "No justification provided.",
        "supporting_image_ids": coerce_supporting_ids(model_out.get("supporting_image_ids"), available_ids),
        "valid_image": _coerce_bool(model_out.get("valid_image"), "false"),
        "severity": _coerce_enum(model_out.get("severity"), SEVERITY, "unknown"),
    }
    return out
