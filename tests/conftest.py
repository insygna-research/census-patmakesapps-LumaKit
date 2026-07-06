import sys
from pathlib import Path

import pytest

# Make the repo root importable regardless of how pytest is invoked.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def workspace(tmp_path):
    """A temp workspace set as the active workspace root."""
    from core.paths import set_workspace_root

    ws = tmp_path / "ws"
    ws.mkdir()
    set_workspace_root(ws)
    return ws
