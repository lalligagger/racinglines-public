from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKE_SCRIPT = ROOT / "scripts" / "deploy" / "smoke.sh"


def test_smoke_gate_does_not_probe_the_failed_login_throttle():
    text = SMOKE_SCRIPT.read_text()
    default_gate = text.split('fi\n\ncheck 200 "GET /login"', 1)[1]

    assert "wrong password" not in default_gate.lower()
    assert "not-the-password" not in default_gate
    assert "GET /markets without credentials" in default_gate
    assert 'MODE="${2:-normal}"' in text
    assert '--auth-throttle' in text
