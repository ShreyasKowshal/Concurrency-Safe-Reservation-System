from pathlib import Path

import yaml

from csrs.config import Settings
from csrs.main import create_app

ROOT = Path(__file__).resolve().parents[3]


def test_health_contract_matches_runtime(settings: Settings) -> None:
    contract = yaml.safe_load((ROOT / "docs/contracts/health.openapi.yaml").read_text("utf-8"))
    runtime = create_app(settings).openapi()
    assert contract["openapi"] == runtime["openapi"]
    assert contract["paths"] == {
        path: value
        for path, value in runtime["paths"].items()
        if path.startswith("/api/v1/health/")
    }
    assert contract["components"]["schemas"] == {
        name: value
        for name, value in runtime["components"]["schemas"].items()
        if name in {"LivenessResponse", "ReadinessResponse"}
    }


def test_complete_implemented_api_contract_matches_runtime(settings: Settings) -> None:
    contract = yaml.safe_load((ROOT / "docs/contracts/api.openapi.yaml").read_text("utf-8"))
    assert contract == create_app(settings).openapi()
