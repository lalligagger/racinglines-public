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


def test_smoke_gate_follows_the_layout_header():
    """Under the alpha layout /live and /book are archived (404 to the demo accounts): the gate reads the app's
    X-Racinglines-Layout header and checks Trade and History instead, and the classic checks stay as they were."""
    text = SMOKE_SCRIPT.read_text()
    assert "%header{x-racinglines-layout}" in text
    alpha, classic = text.split('if [ "$layout" = alpha ]; then', 1)[1].split("else", 1)
    assert "/trade /history" in alpha and "check 404" in alpha and "/live /live/f1 /book/quotes" in alpha
    assert 'check 403 "GET /book/quotes as taker (maker-only)"' in classic


def test_app_sends_the_layout_header(monkeypatch):
    from fastapi.testclient import TestClient

    from racinglines.web.app import app
    client = TestClient(app)
    monkeypatch.setenv("RACINGLINES_LAYOUT", "alpha")
    assert client.get("/login").headers["x-racinglines-layout"] == "alpha"
    monkeypatch.setenv("RACINGLINES_LAYOUT", "classic")
    assert client.get("/login").headers["x-racinglines-layout"] == "classic"
