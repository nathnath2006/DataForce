"""The committed OpenAPI snapshot (source of frontend/src/api.gen.ts) must match the app.

If this fails after an API change, run `make api-types` and commit the two regenerated files.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.api.main import create_app

SNAPSHOT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "openapi.snapshot.json"


def test_openapi_snapshot_is_current():
    live = json.loads(json.dumps(create_app().openapi()))
    assert json.loads(SNAPSHOT.read_text()) == live, "API changed: run `make api-types`"
