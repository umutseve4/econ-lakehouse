"""Unit tests for dashboard/bootstrap.py — no external dependencies needed.

subprocess is stubbed so no real pipeline runs; the e2e fixture-mode
bootstrap is exercised separately in CI (dashboard-smoke job).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import bootstrap  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(name: str, cond: bool) -> None:
    checks.append((name, cond))
    print(f"{name}: {'PASS' if cond else 'FAIL'}")


class _Proc:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def run_all() -> int:
    orig_run = bootstrap.subprocess.run
    orig_key = os.environ.pop("EVDS_API_KEY", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "econ.duckdb"
            existing.write_bytes(b"stub")

            # 1) existing warehouse short-circuits: subprocess must NOT run
            def _explode(*a, **k):  # noqa: ANN002, ANN003
                raise AssertionError("subprocess.run called unexpectedly")

            bootstrap.subprocess.run = _explode
            check("existing_db_short_circuit",
                  bootstrap.ensure_warehouse(existing) == "exists")

            # 2) missing db + successful run that creates it -> built-fixture
            missing = Path(tmp) / "new.duckdb"

            def _ok(*a, **k):  # noqa: ANN002, ANN003
                missing.write_bytes(b"stub")
                return _Proc(0)

            bootstrap.subprocess.run = _ok
            check("fixture_mode_when_no_key",
                  bootstrap.ensure_warehouse(missing) == "built-fixture")

            # 3) with EVDS_API_KEY set -> built-live
            missing2 = Path(tmp) / "new2.duckdb"

            def _ok2(*a, **k):  # noqa: ANN002, ANN003
                missing2.write_bytes(b"stub")
                return _Proc(0)

            os.environ["EVDS_API_KEY"] = "dummy"
            bootstrap.subprocess.run = _ok2
            check("live_mode_when_key_set",
                  bootstrap.ensure_warehouse(missing2) == "built-live")
            del os.environ["EVDS_API_KEY"]

            # 4) pipeline failure -> RuntimeError
            bootstrap.subprocess.run = lambda *a, **k: _Proc(1)
            try:
                bootstrap.ensure_warehouse(Path(tmp) / "fail.duckdb")
                check("pipeline_failure_raises", False)
            except RuntimeError:
                check("pipeline_failure_raises", True)

            # 5) pipeline "succeeds" but produces no warehouse -> RuntimeError
            bootstrap.subprocess.run = lambda *a, **k: _Proc(0)
            try:
                bootstrap.ensure_warehouse(Path(tmp) / "ghost.duckdb")
                check("missing_output_raises", False)
            except RuntimeError:
                check("missing_output_raises", True)
    finally:
        bootstrap.subprocess.run = orig_run
        if orig_key is not None:
            os.environ["EVDS_API_KEY"] = orig_key

    failed = sum(1 for _, ok in checks if not ok)
    print("===== OTOMATIK KONTROL =====")
    print(f"tests_total: {len(checks)}")
    print(f"tests_failed: {failed}")
    print(f"RESULT: {'PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run_all())
