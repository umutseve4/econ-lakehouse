"""The orchestrator's CLI must mean what it says.

`--mode fixture` used to be accepted and ignored: `orchestrate.py` never
looked at `sys.argv`, so the flag that appeared in `run-audit.yml` decided
nothing and the real decision was made by the presence of `EVDS_API_KEY`.
That is the failure these tests exist to prevent — not a crash, but a
readable lie in CI.

Everything here is either pure (`resolve_mode`) or a subprocess that exits
before the pipeline does any work, so this file needs no duckdb, no dbt and
no network.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Explicit, because the way a test file is invoked decides sys.path and the
# quiet version of that mistake costs a red CI run before a single assertion.
sys.path.insert(0, str(ROOT))

from orchestrate import (  # noqa: E402
    FIXTURE_SOURCE,
    LIVE_SOURCE,
    ModeError,
    build_parser,
    resolve_mode,
)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"{name}: {status}" + (f" ({detail})" if detail else ""))
    if not condition:
        FAILURES.append(name)


def run_cli(args: list[str], env_extra: dict | None = None):
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(ROOT / "orchestrate.py"), *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )


# --------------------------------------------------------------- pure ---

def test_fixture_beats_a_present_key() -> None:
    """The acceptance case from issue #49: a key must not override the flag."""
    mode, source = resolve_mode("fixture", "dummy-key-value")
    check("fixture forced despite key -> mode", mode == "fixture", f"got {mode!r}")
    check("fixture forced despite key -> source", source == FIXTURE_SOURCE,
          f"got {source!r}")


def test_fixture_without_key() -> None:
    mode, source = resolve_mode("fixture", "")
    check("fixture without key", mode == "fixture" and source == FIXTURE_SOURCE)


def test_live_without_key_is_an_error() -> None:
    """A missing credential must stop the run, not quietly downgrade it."""
    try:
        resolve_mode("live", "")
    except ModeError as exc:
        msg = str(exc)
        check("live without key raises", True)
        check("live error explains the refusal",
              "EVDS_API_KEY" in msg and "fixture" in msg)
        return
    check("live without key raises", False, "no exception")


def test_live_with_key() -> None:
    mode, source = resolve_mode("live", "k")
    check("live with key", mode == "live" and source == LIVE_SOURCE)


def test_live_ignores_whitespace_only_key() -> None:
    """`EVDS_API_KEY: ${{ secrets.MISSING }}` expands to an empty string."""
    try:
        resolve_mode("live", "   ")
    except ModeError:
        check("whitespace-only key is not a credential", True)
        return
    check("whitespace-only key is not a credential", False, "accepted blank key")


def test_auto_follows_the_environment() -> None:
    no_key = resolve_mode("auto", "")
    with_key = resolve_mode("auto", "k")
    check("auto without key -> fixture", no_key == ("fixture", FIXTURE_SOURCE),
          f"got {no_key!r}")
    check("auto with key -> live", with_key == ("live", LIVE_SOURCE),
          f"got {with_key!r}")


def test_default_is_auto() -> None:
    """Adding the flag must not change how existing callers behave."""
    check("default mode is auto", build_parser().parse_args([]).mode == "auto")


# ---------------------------------------------------------- subprocess ---

def test_unknown_flag_is_a_hard_error() -> None:
    proc = run_cli(["--not-a-real-flag"])
    check("unknown flag exits non-zero", proc.returncode != 0,
          f"exit {proc.returncode}")
    check("unknown flag is reported", "unrecognized arguments" in proc.stderr)


def test_unknown_mode_value_is_rejected() -> None:
    proc = run_cli(["--mode", "prod"])
    check("invalid --mode value exits non-zero", proc.returncode != 0,
          f"exit {proc.returncode}")


def test_live_without_key_exits_non_zero_end_to_end() -> None:
    """Fails fast: no bronze written, no dbt invoked, nothing to clean up."""
    proc = run_cli(["--mode", "live"], env_extra={"EVDS_API_KEY": ""})
    check("--mode live without key exits non-zero", proc.returncode != 0,
          f"exit {proc.returncode}")
    combined = proc.stdout + proc.stderr
    check("--mode live without key explains why", "EVDS_API_KEY" in combined)
    check("--mode live without key ran no pipeline step",
          "step start:" not in combined)


def main() -> int:
    for fn in (
        test_fixture_beats_a_present_key,
        test_fixture_without_key,
        test_live_without_key_is_an_error,
        test_live_with_key,
        test_live_ignores_whitespace_only_key,
        test_auto_follows_the_environment,
        test_default_is_auto,
        test_unknown_flag_is_a_hard_error,
        test_unknown_mode_value_is_rejected,
        test_live_without_key_exits_non_zero_end_to_end,
    ):
        fn()
    print("===== OTOMATIK KONTROL =====")
    print(f"checks_failed: {len(FAILURES)}")
    if FAILURES:
        for name in FAILURES:
            print(f"  failed: {name}")
    print(f"RESULT: {'PASS' if not FAILURES else 'FAIL'}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    raise SystemExit(main())
