"""Regenerate the implemented contract intentionally after reviewing endpoint changes."""

from pathlib import Path

import yaml

from csrs.config import Settings
from csrs.main import create_app

settings = Settings(
    environment="test",
    database_url="postgresql+psycopg://example:example@localhost/csrs_test",
    redis_url="redis://localhost:6379/0",
)
contract = create_app(settings).openapi()
directory = Path(__file__).resolve().parents[2] / "docs/contracts"
(directory / "api.openapi.yaml").write_text(
    yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
)
health = {
    **contract,
    "paths": {
        path: value
        for path, value in contract["paths"].items()
        if path.startswith("/api/v1/health/")
    },
    "components": {
        "schemas": {
            name: value
            for name, value in contract["components"]["schemas"].items()
            if name in {"LivenessResponse", "ReadinessResponse"}
        }
    },
}
(directory / "health.openapi.yaml").write_text(
    yaml.safe_dump(health, sort_keys=False), encoding="utf-8"
)
