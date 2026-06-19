from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrate.bedrock_client import BedrockVLM
from orchestrate.config import SETTINGS
from orchestrate.data import load_claims, missing_images
from orchestrate.pipeline import run_claims, write_output


def main() -> int:
    ap = argparse.ArgumentParser(description="Multi-modal evidence review runner")
    ap.add_argument("--claims", default=str(SETTINGS.test_csv), help="input claims CSV")
    ap.add_argument("--out", default=str(SETTINGS.dataset_dir.parent / "output.csv"),
                    help="output CSV path (default: repo-root/output.csv)")
    ap.add_argument("--variant", choices=["full", "full_rf", "base", "lean"], default="full")
    ap.add_argument("--fewshot", action="store_true", help="prepend few-shot exemplars (recommended)")
    ap.add_argument("--limit", type=int, default=0, help="only process first N claims")
    ap.add_argument("--workers", type=int, default=SETTINGS.max_workers)
    args = ap.parse_args()

    claims = load_claims(Path(args.claims), is_labeled=False)
    if args.limit:
        claims = claims[: args.limit]

    miss = missing_images(claims)
    if miss:
        print(f"[warn] {len(miss)} referenced image(s) missing on disk, e.g. {miss[:3]}",
              file=sys.stderr)

    print(f"[info] model={SETTINGS.model_id} region={SETTINGS.region} "
          f"mock={SETTINGS.mock} variant={args.variant} fewshot={args.fewshot} claims={len(claims)}")

    vlm = BedrockVLM()
    rows, vlm = run_claims(claims, variant=args.variant, fewshot=args.fewshot,
                           vlm=vlm, max_workers=args.workers)

    out_path = Path(args.out)
    write_output(rows, out_path)
    print(f"[done] wrote {len(rows)} rows -> {out_path}")
    print("[usage] " + json.dumps(vlm.usage.as_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
