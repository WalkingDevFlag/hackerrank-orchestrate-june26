from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .config import SETTINGS


@dataclass
class Claim:
    user_id: str
    image_paths: str
    user_claim: str
    claim_object: str
    image_files: list[Path] = field(default_factory=list)
    image_ids: list[str] = field(default_factory=list)
    history: dict = field(default_factory=dict)
    evidence_rules: list[dict] = field(default_factory=list)
    expected: dict | None = None


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_user_history(path: Path | None = None) -> dict[str, dict]:
    path = path or SETTINGS.user_history_csv
    return {r["user_id"]: r for r in _read_csv(path)}


def load_evidence_rules(path: Path | None = None) -> list[dict]:
    path = path or SETTINGS.evidence_csv
    return _read_csv(path)


def _match_evidence(rules: list[dict], claim_object: str) -> list[dict]:
    return [r for r in rules if r["claim_object"] in (claim_object, "all")]


def _resolve_images(image_paths: str) -> tuple[list[Path], list[str]]:
    files, ids = [], []
    for raw in image_paths.split(";"):
        raw = raw.strip()
        if not raw:
            continue
        p = (SETTINGS.images_root / raw).resolve()
        files.append(p)
        ids.append(Path(raw).stem)
    return files, ids


def load_claims(
    csv_path: Path,
    *,
    is_labeled: bool = False,
    history: dict[str, dict] | None = None,
    evidence: list[dict] | None = None,
) -> list[Claim]:
    history = history if history is not None else load_user_history()
    evidence = evidence if evidence is not None else load_evidence_rules()
    rows = _read_csv(csv_path)
    claims: list[Claim] = []
    for r in rows:
        files, ids = _resolve_images(r["image_paths"])
        expected = None
        if is_labeled:
            from .schema import MODEL_FIELDS
            expected = {k: r.get(k, "") for k in MODEL_FIELDS}
        claims.append(
            Claim(
                user_id=r["user_id"],
                image_paths=r["image_paths"],
                user_claim=r["user_claim"],
                claim_object=r["claim_object"],
                image_files=files,
                image_ids=ids,
                history=history.get(r["user_id"], {}),
                evidence_rules=_match_evidence(evidence, r["claim_object"]),
                expected=expected,
            )
        )
    return claims


def missing_images(claims: list[Claim]) -> list[str]:
    missing = []
    for c in claims:
        for f in c.image_files:
            if not f.exists():
                missing.append(str(f))
    return missing
