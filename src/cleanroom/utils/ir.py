"""Canonical IR shape and normalization — single source for field names across agents.

The spec-stage IR uses:
  * Feature.id          (not feature_id)
  * FunctionalRequirement.text  (not description)
  * TestCase.inputs_json / expected_json  (oracle fields; inputs/expected are human summaries)

Legacy artifacts (cached JSON, raw parser output) may still use the old names; call
``normalize_ir_features`` / ``normalize_generated_tests`` at agent entry points.
"""

from __future__ import annotations

import json
from typing import Any


def feature_id_of(feature: dict) -> str:
    """Return the canonical feature id from either ``id`` or legacy ``feature_id``."""
    return feature.get("id") or feature.get("feature_id") or ""


def requirement_text(fr: dict) -> str:
    """Return requirement prose — canonical field is ``text``; legacy ``description`` accepted."""
    return fr.get("text") or fr.get("description") or ""


def normalize_fr(fr: dict) -> dict:
    """Ensure an FR dict uses canonical ``id`` and ``text``."""
    out = dict(fr)
    text = requirement_text(out)
    if text:
        out["text"] = text
    return out


def normalize_feature(feature: dict) -> dict:
    """Ensure a feature dict uses canonical ``id`` and normalized FRs."""
    out = dict(feature)
    fid = feature_id_of(out)
    if fid:
        out["id"] = fid
    if "feature_id" in out and out.get("feature_id") == out.get("id"):
        out.pop("feature_id", None)
    frs = out.get("functional_requirements") or []
    out["functional_requirements"] = [normalize_fr(r) for r in frs]
    return out


def normalize_ir_features(ir: dict) -> dict:
    """Normalize feature/FR field names in place; return the IR."""
    features = ir.get("features")
    if features is not None:
        ir["features"] = [normalize_feature(f) for f in features]
    return ir


def normalize_test_case(case: dict) -> dict:
    """Ensure a test case has oracle fields required by the certification runner."""
    out = dict(case)
    out.setdefault("inputs_json", "{}")
    out.setdefault("expected_json", "null")
    out.setdefault("oracle", "eq")
    out.setdefault("description", "")
    out.setdefault("inputs", "")
    out.setdefault("expected", "")
    rid = out.get("requirement_id") or out.get("fr_id")
    if rid:
        out["requirement_id"] = rid
    return out


def normalize_generated_tests(tests: dict) -> dict:
    """Normalize test artifacts in place; return the dict."""
    features = tests.get("features")
    if not features:
        return tests
    normalized: list[dict] = []
    for feature in features:
        f = dict(feature)
        cases = f.get("cases") or []
        f["cases"] = [normalize_test_case(c) for c in cases]
        normalized.append(f)
    tests["features"] = normalized
    return tests


def normalize_ir(ir: dict) -> dict:
    """Apply all in-place IR normalizations agents expect."""
    normalize_ir_features(ir)
    if ir.get("generated_tests"):
        normalize_generated_tests(ir["generated_tests"])
    return ir
