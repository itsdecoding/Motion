import json
from pathlib import Path

import pytest

from engine.config import ROOT


@pytest.fixture
def spec() -> dict:
    return json.loads((ROOT / "examples" / "outbound.json").read_text(encoding="utf-8"))
