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
destination = Path(__file__).resolve().parents[2] / "docs/contracts/health.openapi.yaml"
destination.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
