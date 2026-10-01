"""
Quick checks as tests (no network, no database, no downloaded data): the real pipelines on
small synthetic data. Same checks as `racinglines check --offline --no-db`.
"""

import pytest

from racinglines.testing import checks as C

pytestmark = pytest.mark.quick

def test_code_checks():
    """Run in order (later checks use earlier state); report every failure."""
    failed = [f"{r.group}/{r.name}: {r.detail}" for r in C.run_code() if not r.ok]
    assert not failed, "\n".join(failed)
