import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location(
    "fetch_test_fixtures",
    ROOT / "scripts" / "fetch_test_fixtures.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_fixture_downloads_are_explicit_and_minimal():
    assert mod.ALLOWED_FIXTURE_TARGETS == ("f1", "mtb")
    assert mod.download_targets(f1=True, mtb=False) == ("f1",)
    assert mod.download_targets(f1=False, mtb=True) == ("mtb",)
    assert mod.download_targets(f1=True, mtb=True) == ("f1", "mtb")
    assert mod.download_targets(f1=False, mtb=False) == ("f1", "mtb")

    try:
        mod.download_targets(f1=False, mtb=False, extra=True)  # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError("unsupported kwargs should not be accepted")
