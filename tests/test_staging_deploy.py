"""Staging on the VM (docs/vm-deploy.md "Staging") stays apart from production: static checks of the scripts,
the unit and the workflow, so a later edit can't quietly make `vm.sh staging deploy` touch production."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VM_SH = (ROOT / "scripts/deploy/vm.sh").read_text()
UPDATE = (ROOT / "deploy/vm/staging/update.sh").read_text()
SETUP = (ROOT / "deploy/vm/staging/setup.sh").read_text()
UNIT = (ROOT / "deploy/vm/systemd/racinglines-staging-web.service").read_text()
WORKFLOW = (ROOT / "deploy/ci/staging.yml").read_text()


def code(text):
    """The script without its comment lines (comments may name what the code must not do)."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def staging_block():
    return code(VM_SH.split("\n  staging)\n", 1)[1].split("\n  status)\n", 1)[0])


def test_vm_sh_staging_never_pauses_or_deploys_production():
    block = staging_block()
    assert "/opt/racinglines-staging" in block
    for forbidden in ("$PAUSED", "systemctl stop", "untrack.sh", "deploy/vm/update.sh", "racinglines-web ", "racinglines-recorder",
                      "racinglines-signals", "racinglines-live", "/etc/racinglines.env", "$SERVICES"):
        assert forbidden not in block, forbidden
    assert "SMOKE_EXPECT_ENV=staging" in block


def test_staging_update_migrates_only_the_staging_database():
    UPDATE = code(globals()["UPDATE"])
    assert "/opt/racinglines-staging" in UPDATE
    assert "/etc/racinglines-staging.env" in UPDATE
    assert "*/$DB) ;;" in UPDATE and "DB=racinglines_staging" in UPDATE
    assert "docker compose up" not in UPDATE
    assert "cd /opt/racinglines\n" not in UPDATE


def test_staging_setup_only_reads_production():
    SETUP = code(globals()["SETUP"])
    assert "RESET_DB" in SETUP
    assert "pg_dump --no-owner --no-privileges -U racinglines racinglines" in SETUP
    assert "psql -q -U racinglines -d $DB" in SETUP
    assert "grep -viE 'TRADING'" in SETUP
    assert "RACINGLINES_ENV=staging" in SETUP and "WEB_PORT=8010" in SETUP
    assert "racinglines-staging-web" in SETUP
    for forbidden in ("systemctl restart racinglines-web", "systemctl stop", "DROP DATABASE IF EXISTS racinglines "):
        assert forbidden not in SETUP, forbidden


def test_staging_unit_is_its_own_instance():
    assert "WorkingDirectory=/opt/racinglines-staging" in UNIT
    assert "EnvironmentFile=/etc/racinglines-staging.env" in UNIT
    assert "WEB_PORT=8010" in UNIT
    assert "/opt/racinglines-staging/.venv/bin/racinglines web" in UNIT


def test_staging_workflow_deploys_staging_only():
    assert re.search(r"branches: \[staging\]", WORKFLOW)
    assert "vm.sh staging deploy" in WORKFLOW
    assert "SMOKE_EXPECT_ENV=staging" in WORKFLOW
    wf = code(WORKFLOW)
    assert "predeploy.sh --prod" not in wf and "vm.sh deploy " not in wf


def test_env_header_and_label_are_off_by_default(monkeypatch):
    monkeypatch.delenv("RACINGLINES_ENV", raising=False)
    from racinglines.web import app as web_app
    assert web_app.ENV_LABEL == ""
    assert web_app.templates.env.globals["env_label"]() == ""
