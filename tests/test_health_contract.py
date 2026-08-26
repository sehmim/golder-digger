"""The desktop app and the engine agree about which routes exist.

`src/main/api.ts` adopts an already-listening server rather than spawning a
second one, which is the right call for a `golddigger serve` you left in a
terminal and the wrong call for one older than the routes the app now needs.
The guard used to be a single marker key somebody had to remember to move; it
was never moved, so from the first commit to this one it was present in every
build and discriminated nothing. /health now publishes its own route table and
the app names what it requires, and this test is what keeps the two honest.
"""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from goldigger import api

CLIENT = Path(__file__).resolve().parents[1] / "golders-desktop/src/main/api.ts"


def required_routes() -> list[str]:
    """The REQUIRED_ROUTES literal, read out of the TypeScript itself.

    Parsed rather than duplicated: a copy here would be one more pair of lists
    that can drift, which is the bug this file exists to prevent.
    """
    source = CLIENT.read_text()
    block = re.search(r"const REQUIRED_ROUTES\s*=\s*\[(.*?)\]", source, re.S)
    assert block, f"no REQUIRED_ROUTES literal in {CLIENT}"
    return re.findall(r"'([^']+)'", block.group(1))


def test_the_app_publishes_its_own_route_table():
    body = TestClient(api.app).get("/health").json()
    assert isinstance(body.get("routes"), list) and body["routes"]
    assert "/session/lines" in body["routes"]


def test_every_route_the_desktop_requires_exists():
    served = {r.path for r in api.app.routes if getattr(r, "methods", None)}
    missing = [p for p in required_routes() if p not in served]
    assert not missing, f"{CLIENT.name} requires routes the engine does not serve: {missing}"


def test_the_required_list_is_not_empty():
    """An empty list would pass the subset check against any server at all."""
    assert len(required_routes()) >= 5
