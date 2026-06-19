from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import SETTINGS


@dataclass
class UsageMeter:
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    images: int = 0
    wall_seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "model_calls": self.calls,
            "cache_hits": self.cache_hits,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "images_processed": self.images,
            "wall_seconds": round(self.wall_seconds, 2),
        }


class _Cache:
    def __init__(self, root: Path, enabled: bool):
        self.root = root
        self.enabled = enabled
        if enabled:
            root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> dict | None:
        if not self.enabled:
            return None
        p = self._path(key)
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                return None
        return None

    def put(self, key: str, value: dict) -> None:
        if not self.enabled:
            return
        try:
            self._path(key).write_text(json.dumps(value))
        except Exception:
            pass


def _cache_key(model_id: str, system: str, content_blocks: list[dict], temperature: float) -> str:
    h = hashlib.sha256()
    h.update(model_id.encode())
    h.update(f"|temp={temperature}|".encode())
    h.update(system.encode())
    for b in content_blocks:
        if b.get("type") == "text":
            h.update(b["text"].encode())
        elif b.get("type") == "image":
            h.update(b["source"]["data"].encode())
    return h.hexdigest()[:32]


class BedrockVLM:

    def __init__(self, settings=SETTINGS):
        self.s = settings
        self.usage = UsageMeter()
        self.cache = _Cache(settings.cache_dir, settings.use_cache)
        self._client = None
        if not settings.mock:
            import boto3

            self._client = boto3.client("bedrock-runtime", region_name=settings.region)

    def complete_json(self, system: str, content_blocks: list[dict], n_images: int = 0) -> dict:
        key = _cache_key(self.s.model_id, system, content_blocks, self.s.temperature)
        cached = self.cache.get(key)
        if cached is not None:
            self.usage.cache_hits += 1
            return cached["parsed"]

        if self.s.mock:
            parsed = _mock_response(content_blocks)
        else:
            parsed = self._invoke_with_retry(system, content_blocks)

        self.usage.images += n_images
        self.cache.put(key, {"parsed": parsed})
        return parsed

    def _invoke_with_retry(self, system: str, content_blocks: list[dict]) -> dict:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self.s.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content_blocks}],
        }
        if "opus-4-8" not in self.s.model_id:
            body["temperature"] = self.s.temperature
        last_err: Exception | None = None
        for attempt in range(self.s.max_retries):
            try:
                t0 = time.time()
                resp = self._client.invoke_model(
                    modelId=self.s.model_id, body=json.dumps(body)
                )
                self.usage.wall_seconds += time.time() - t0
                payload = json.loads(resp["body"].read())
                self.usage.calls += 1
                usage = payload.get("usage", {})
                self.usage.input_tokens += usage.get("input_tokens", 0)
                self.usage.output_tokens += usage.get("output_tokens", 0)
                text = "".join(
                    b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"
                )
                return _extract_json(text)
            except Exception as e:
                last_err = e
                name = type(e).__name__
                transient = any(
                    k in name for k in ("Throttling", "TooManyRequests", "Timeout", "ServiceUnavailable", "ModelError")
                )
                if attempt == self.s.max_retries - 1 or not transient:
                    if not transient:
                        raise
                    break
                sleep = self.s.base_backoff * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(sleep)
        raise RuntimeError(f"Bedrock call failed after retries: {last_err}")


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def _mock_response(content_blocks: list[dict]) -> dict:
    has_image = any(b.get("type") == "image" for b in content_blocks)
    return {
        "evidence_standard_met": True if has_image else False,
        "evidence_standard_met_reason": "[MOCK] plumbing test response.",
        "visual_risk_flags": [],
        "issue_type": "unknown",
        "object_part": "unknown",
        "claim_status": "not_enough_information",
        "claim_status_justification": "[MOCK] no real model was called.",
        "supporting_image_ids": [],
        "valid_image": True if has_image else False,
        "severity": "unknown",
    }
