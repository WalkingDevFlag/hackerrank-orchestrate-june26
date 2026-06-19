from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"


@dataclass
class Settings:
    dataset_dir: Path = DATASET_DIR
    sample_csv: Path = field(default_factory=lambda: DATASET_DIR / "sample_claims.csv")
    test_csv: Path = field(default_factory=lambda: DATASET_DIR / "claims.csv")
    user_history_csv: Path = field(default_factory=lambda: DATASET_DIR / "user_history.csv")
    evidence_csv: Path = field(default_factory=lambda: DATASET_DIR / "evidence_requirements.csv")
    images_root: Path = DATASET_DIR

    region: str = os.environ.get("AWS_REGION", "us-west-2")
    model_id: str = os.environ.get(
        "BEDROCK_MODEL_ID",
        "us.anthropic.claude-opus-4-5-20251101-v1:0",
    )
    temperature: float = float(os.environ.get("ORCH_TEMPERATURE", "0"))
    max_tokens: int = int(os.environ.get("ORCH_MAX_TOKENS", "1200"))

    max_image_dim: int = int(os.environ.get("ORCH_MAX_IMAGE_DIM", "1024"))
    jpeg_quality: int = int(os.environ.get("ORCH_JPEG_QUALITY", "85"))

    max_retries: int = int(os.environ.get("ORCH_MAX_RETRIES", "5"))
    base_backoff: float = float(os.environ.get("ORCH_BASE_BACKOFF", "2.0"))
    max_workers: int = int(os.environ.get("ORCH_MAX_WORKERS", "4"))
    cache_dir: Path = field(default_factory=lambda: REPO_ROOT / "code" / ".cache")
    use_cache: bool = os.environ.get("ORCH_USE_CACHE", "1") != "0"

    mock: bool = os.environ.get("ORCH_MOCK", "0") == "1"


SETTINGS = Settings()
