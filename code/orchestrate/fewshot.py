from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .config import SETTINGS
from .images import load_image_b64

EXEMPLARS = [
    {
        "case": "sample/case_001", "object": "car",
        "chat": "Customer: new dent on my car after parking outside overnight; rear bumper area.",
        "answer": {
            "evidence_standard_met": True, "visual_risk_flags": [],
            "issue_type": "dent", "object_part": "rear_bumper",
            "claim_status": "supported",
            "claim_status_justification": "img_1 clearly shows a dent on the rear bumper.",
            "supporting_image_ids": ["img_1"], "valid_image": True, "severity": "medium",
        },
        "note": "Clear single-area dent -> supported, severity MEDIUM (the default for real damage, not high).",
    },
    {
        "case": "sample/case_005", "object": "car",
        "chat": "Customer: car tapped from behind, rear bumper, looks pretty bad to me.",
        "answer": {
            "evidence_standard_met": True, "visual_risk_flags": ["claim_mismatch"],
            "issue_type": "scratch", "object_part": "rear_bumper",
            "claim_status": "contradicted",
            "claim_status_justification": "img_1 shows only minor rear-bumper scratching, not the severe damage claimed.",
            "supporting_image_ids": ["img_1"], "valid_image": True, "severity": "low",
        },
        "note": "Customer overstates severity; photo shows only a minor scratch -> contradicted, severity LOW.",
    },
    {
        "case": "sample/case_009", "object": "laptop",
        "chat": "Customer: laptop fell, the display glass has a crack now; screen only.",
        "answer": {
            "evidence_standard_met": True, "visual_risk_flags": [],
            "issue_type": "crack", "object_part": "screen",
            "claim_status": "supported",
            "claim_status_justification": "img_1 shows crack lines on the laptop screen.",
            "supporting_image_ids": ["img_1"], "valid_image": True, "severity": "medium",
        },
        "note": "A single crack line on a screen is issue_type=crack (NOT glass_shatter), severity MEDIUM.",
    },
    {
        "case": "sample/case_006", "object": "car",
        "chat": "Customer: walked around the car, think the headlight may be cracked; review the headlight.",
        "answer": {
            "evidence_standard_met": False, "visual_risk_flags": ["wrong_angle", "damage_not_visible"],
            "issue_type": "unknown", "object_part": "headlight",
            "claim_status": "not_enough_information",
            "claim_status_justification": "The submitted image does not show the headlight, so the crack cannot be verified.",
            "supporting_image_ids": [], "valid_image": True, "severity": "unknown",
        },
        "note": "Claimed part (headlight) is not shown -> not_enough_information; issue_type/severity unknown; no manual review (benign history).",
    },
    {
        "case": "sample/case_002", "object": "car",
        "chat": "Customer (Hinglish): front bumper par scratch hai; photos upload kar diye.",
        "answer": {
            "evidence_standard_met": False, "visual_risk_flags": ["wrong_object", "claim_mismatch"],
            "issue_type": "broken_part", "object_part": "front_bumper",
            "claim_status": "not_enough_information",
            "claim_status_justification": "The close-up (img_1) and full view (img_2) appear to be different cars, so the damage cannot be tied to the claimed vehicle.",
            "supporting_image_ids": ["img_1", "img_2"], "valid_image": True, "severity": "unknown",
        },
        "note": "Identity mismatch -> not_enough_information ONLY because NEITHER image independently shows the claimed part with the claimed-kind damage on one consistent vehicle (the close-up's damage cannot be attributed to a differently-looking full view). If ONE image alone had clearly shown the claimed scratch on the claimed bumper, the answer would be supported despite the mismatch. Flag wrong_object + claim_mismatch; cite both IDs.",
    },
    {
        "case": "sample/case_015", "object": "package",
        "chat": "Customer: delivery box arrived with one corner crushed in; package corner damage.",
        "answer": {
            "evidence_standard_met": True, "visual_risk_flags": [],
            "issue_type": "crushed_packaging", "object_part": "package_corner",
            "claim_status": "supported",
            "claim_status_justification": "img_1 shows crushing on the package corner.",
            "supporting_image_ids": ["img_1"], "valid_image": True, "severity": "medium",
        },
        "note": "Crushed package corner -> supported, issue_type=crushed_packaging, severity MEDIUM.",
    },
]

EXEMPLAR_USER_IDS = {"user_001", "user_005", "user_009", "user_006", "user_002", "user_015"}


@lru_cache(maxsize=1)
def build_exemplar_blocks(k: int = 6) -> tuple:
    blocks: list[dict] = []
    blocks.append({
        "type": "text",
        "text": (
            "Here are labeled REFERENCE EXAMPLES showing the expected output conventions. "
            "Study how severity, issue_type, claim_status, and flags are assigned, then apply "
            "the SAME conventions to the actual claim that follows. (These are reference only.)"
        ),
    })
    for i, ex in enumerate(EXEMPLARS[:k], 1):
        case_dir = SETTINGS.dataset_dir / "images" / Path(ex["case"])
        imgs = sorted(p for p in case_dir.glob("*") if p.is_file() and not p.name.startswith("."))
        ids = [p.stem for p in imgs]
        blocks.append({"type": "text", "text": f"--- REFERENCE EXAMPLE {i} (object={ex['object']}; image IDs: {', '.join(ids)}) ---"})
        for p, img_id in zip(imgs, ids):
            b64, mt = load_image_b64(p)
            blocks.append({"type": "text", "text": f"IMAGE_ID: {img_id}"})
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}})
        blocks.append({"type": "text", "text": f"Chat: {ex['chat']}"})
        blocks.append({"type": "text", "text": "Correct answer:\n" + json.dumps(ex["answer"])})
        blocks.append({"type": "text", "text": f"Why: {ex['note']}"})
    blocks.append({"type": "text", "text": "--- END REFERENCE EXAMPLES. Now adjudicate the ACTUAL claim below. ---"})
    return tuple(blocks)
