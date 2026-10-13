"""Staging on the VM (docs/vm-deploy.md "Staging") stays apart from production: static checks of the scripts,
the unit and the workflow, so a later edit can't quietly make `vm.sh staging deploy` touch production."""
import re
import subprocess
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


# --- production and staging never share a venv (docs/vm-deploy.md "Separate venvs") ---
PROD_UPDATE = (ROOT / "deploy/vm/update.sh").read_text()
PROD_SETUP = (ROOT / "deploy/vm/setup.sh").read_text()


def _guard_source(text):
    return text.split("venv_guard() {", 1)[1].split("\n}\n", 1)[0]


def test_every_deploy_script_guards_the_venvs():
    guards = {_guard_source(t) for t in (UPDATE, SETUP, PROD_UPDATE, PROD_SETUP)}
    assert len(guards) == 1, "the four copies of venv_guard drifted apart"
    for text in (UPDATE, PROD_UPDATE):
        body = code(text).split("main() {", 1)[1]
        assert body.index("venv_guard") < body.index("git "), "venv_guard must run before the checkout changes"
        assert body.index("pip install") < body.index("imports_here")
    for text in (SETUP, PROD_SETUP):
        body = code(text)
        assert body.index("\nvenv_guard") < body.index("uv venv")
    # vm.sh checks before it pauses timers (production) or deploys (staging)
    prod = code(VM_SH.split("\n  deploy)\n", 1)[1])
    assert prod.index("venv_check") < prod.index("$PAUSED")
    stg = staging_block().split("\n      deploy)\n", 1)[1]
    assert stg.index("venv_check") < stg.index("staging/update.sh")


def _run_guard(tmp_path, p, s):
    script = "venv_guard() {" + _guard_source(PROD_UPDATE) + "\n}\nvenv_guard \"$1\" \"$2\"\n"
    return subprocess.run(["bash", "-c", script, "guard", str(p), str(s)], capture_output=True, text=True, check=False)


def test_venv_guard_refuses_a_symlink_or_the_same_venv(tmp_path):
    prod, stg = tmp_path / "prod.venv", tmp_path / "stg.venv"
    prod.mkdir()
    assert _run_guard(tmp_path, prod, stg).returncode == 0          # staging not set up yet
    stg.symlink_to(prod)
    r = _run_guard(tmp_path, prod, stg)
    assert r.returncode == 1 and "is a symlink" in r.stdout
    stg.unlink()
    stg.mkdir()
    assert _run_guard(tmp_path, prod, stg).returncode == 0          # two venvs
    r = _run_guard(tmp_path, prod, tmp_path / "." / "prod.venv")
    assert r.returncode == 1 and "same venv" in r.stdout


def test_vm_sh_venv_check_refuses_the_same_way(tmp_path):
    snippet = VM_SH.split("venv_check() {\n  remote '", 1)[1].split("' ||", 1)[0]
    prod, stg = tmp_path / "p", tmp_path / "s"
    prod.mkdir()
    stg.symlink_to(prod)
    snippet = snippet.replace("/opt/racinglines/.venv", str(prod)).replace("/opt/racinglines-staging/.venv", str(stg))
    r = subprocess.run(["bash", "-c", snippet], capture_output=True, text=True, check=False)
    assert r.returncode == 1 and "is a symlink" in r.stdout
    stg.unlink()
    stg.mkdir()
    assert subprocess.run(["bash", "-c", snippet], check=False).returncode == 0


def _deploy_wait(tmp_path, active):
    """Run vm.sh deploy's wait step locally with a fake systemctl: -> (exit code, units it stopped)."""
    line = next(ln for ln in VM_SH.splitlines() if "seq 60" in ln and "activating" in ln)
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    stopped = tmp_path / "stopped"
    stopped.write_text("")
    (fake / "systemctl").write_text('#!/bin/bash\nif [ "$1" = stop ]; then echo "$2" >> "$STOPPED"; exit 0; fi\n'
                                    'for u in $ACTIVE; do echo "$u loaded activating start x"; done\n')
    (fake / "sudo").write_text('#!/bin/bash\n"$@"\n')
    (fake / "seq").write_text("#!/bin/bash\necho 1\n")
    (fake / "sleep").write_text("#!/bin/bash\n")
    for f in fake.iterdir():
        f.chmod(0o755)
    script = ('remote() { bash -c "$1"; }\nsteps=" racinglines-signals.service racinglines-live-f1@x.service"\nrc=0\n'
              + line.strip() + '\nexit "$rc"\n')
    env = {"PATH": f"{fake}:/usr/bin:/bin", "ACTIVE": active, "STOPPED": str(stopped)}
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=False)
    return r.returncode, stopped.read_text().split()


def test_deploy_stops_a_slow_signals_pass_but_waits_for_live_steps(tmp_path):
    assert _deploy_wait(tmp_path, "") == (0, [])
    assert _deploy_wait(tmp_path, "racinglines-signals.service") == (0, ["racinglines-signals.service"])
    assert _deploy_wait(tmp_path, "racinglines-live-f1@x.service racinglines-signals.service") == (1, [])
    assert _deploy_wait(tmp_path, "racinglines-live-f1@x.service") == (1, [])
