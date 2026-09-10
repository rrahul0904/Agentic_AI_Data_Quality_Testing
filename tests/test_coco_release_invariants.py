from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI

import agentic_data_platform.api as api_package
from agentic_data_platform.api import create_app
from agentic_data_platform.api.app import create_app as legacy_create_app


ROOT = Path(__file__).resolve().parents[1]
PROMOTER_PATH = ROOT / "scripts" / "promote_coco_ledger.py"
CERTIFICATION_PATH = "/api/v1/certification/coco"


def _load_promoter():
    spec = importlib.util.spec_from_file_location("promote_coco_ledger", PROMOTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _routes(application: FastAPI) -> set[tuple[str, str]]:
    return {
        (route.path, method)
        for route in application.routes
        for method in getattr(route, "methods", set())
    }


def test_create_app_returns_fastapi_and_certification_get_is_registered():
    legacy_application = legacy_create_app()
    assert isinstance(legacy_application, FastAPI)

    application = create_app()
    assert isinstance(application, FastAPI)
    assert (CERTIFICATION_PATH, "GET") in _routes(application)


def test_api_factory_keeps_certification_route_after_package_reload():
    """Regression guard for full-suite/embedded import lifecycles."""

    reloaded = importlib.reload(api_package)
    application = reloaded.create_app()
    assert isinstance(application, FastAPI)
    assert (CERTIFICATION_PATH, "GET") in _routes(application)

    # A second reload must remain safe and must not recurse through a previously
    # installed compatibility wrapper or duplicate the certification endpoint.
    reloaded = importlib.reload(reloaded)
    application = reloaded.create_app()
    assert isinstance(application, FastAPI)
    matching = [
        route
        for route in application.routes
        if getattr(route, "path", None) == CERTIFICATION_PATH
        and "GET" in (getattr(route, "methods", set()) or set())
    ]
    assert len(matching) == 1


def test_ledger_promotion_fails_closed_on_stale_golden_sha():
    promoter = _load_promoter()
    ledger = {
        "capabilities": [
            {
                "id": "local.capability",
                "certification_track": promoter.COCO_TRACK,
                "ade_current": "partial",
            }
        ]
    }
    golden = {
        "status": "PASS",
        "scenario_count": 8,
        "passed": 8,
        "failed": 0,
        "head_sha": "old-head",
        "results": [
            {
                "id": "GS01",
                "status": "PASS",
                "certification_track": promoter.COCO_TRACK,
                "capabilities": ["local.capability"],
            }
        ],
    }

    with pytest.raises(ValueError, match="exact-head mismatch"):
        promoter.promote(ledger, golden, head="new-head")


def test_ledger_promotion_never_promotes_extensions_or_superiority():
    promoter = _load_promoter()
    ledger = {
        "capabilities": [
            {
                "id": "local.capability",
                "certification_track": promoter.COCO_TRACK,
                "ade_current": "partial",
                "target_score": 2,
            },
            {
                "id": "extension.capability",
                "certification_track": "ADE_EXTENSION_ASSURANCE",
                "ade_current": "partial",
                "target_score": 2,
            },
        ]
    }
    golden = {
        "status": "PASS",
        "scenario_count": 8,
        "passed": 8,
        "failed": 0,
        "head_sha": "same-head",
        "results": [
            {
                "id": "GS01",
                "status": "PASS",
                "certification_track": promoter.COCO_TRACK,
                "capabilities": ["local.capability"],
            },
            {
                "id": "GS08",
                "status": "PASS",
                "certification_track": "ADE_EXTENSION_ASSURANCE",
                "capabilities": ["extension.capability"],
            },
        ],
    }

    updated, promoted = promoter.promote(ledger, golden, head="same-head")
    by_id = {item["id"]: item for item in updated["capabilities"]}
    assert promoted == ["local.capability"]
    assert by_id["local.capability"]["ade_current"] == "implemented_on_branch"
    assert by_id["local.capability"]["target_score"] == 2
    assert by_id["extension.capability"]["ade_current"] == "partial"
    assert by_id["extension.capability"]["target_score"] == 2
    assert all(item["ade_current"] != "superior" for item in updated["capabilities"])
