from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "hospitality_testbed"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture(scope="session")
def generated_dataset(tmp_path_factory):
    from generate_data import build_dataset
    from lib import load_yaml

    root = tmp_path_factory.mktemp("hospitality")
    config = load_yaml("hospitality_testbed.yml")
    settings = {
        **config["defaults"],
        **config["presets"]["tiny"],
        "preset": "test",
        "seed": 42,
        "hotels": 2,
        "guests": 100,
        "reservations": 200,
        "rows_per_file": 50,
    }
    manifest = build_dataset(settings, root, record_runtime=False)
    return root, manifest, settings
