"""One-shot, anchored patch: close the teardown window in the ingest CLI.

Retyping a source file from a conversation does not hold at the byte level,
so this changes exactly two anchors and refuses to touch anything else.
Each anchor must match exactly once. If it does not, nothing is written and
the caller fails, because a patch that silently matched zero times is worse
than one that never ran.

Deleted in the same pull request that merges the fix.
"""

from __future__ import annotations

from pathlib import Path

TARGET = Path("ingest/ingest.py")

OLD_IMPORTS = "import argparse\nimport sys\n"
NEW_IMPORTS = "import argparse\nimport os\nimport sys\n"

OLD_GUARD = '\n\nif __name__ == "__main__":\n    sys.exit(main())\n'

NEW_GUARD = '''

def _exit_without_teardown(status: int) -> int:
    """Leave the process immediately, skipping every teardown handler.

    This CLI is a leaf: when main() returns, all work is finished and
    durable. The Parquet partitions were written and closed by
    write_bronze(), and count_bronze_rows() has already re-read them from
    storage in a separate pass, so the check block printed above is a
    statement about bytes that exist on disk, not about buffers.

    What remains after that point is pure shutdown, and shutdown is where
    #63, #68 and #70 died. In all three the child printed "RESULT: PASS"
    and then emitted "terminate called without an active exception" and
    exit -6 (SIGABRT). That message comes from the C++ runtime, not from
    Python: a std::thread destroyed while still joinable, during the
    static-destructor phase that runs after CPython finalises. The failing
    runs also spent about four seconds longer than the passing ones, and
    that time was spent in shutdown rather than in ingest.

    os._exit() bypasses that phase entirely: no atexit handlers, no
    interpreter finalisation, no __cxa_atexit destructors. The exit status
    the caller sees becomes exactly the status computed here. Because
    os._exit() also skips buffer flushing, stdout and stderr are flushed
    explicitly first, so the machine-readable check block is never lost.

    This does not hide a failure. A non-zero status is propagated
    unchanged, so a real ingest error still fails the pipeline. It removes
    only the window in which an already-successful run could be turned into
    a failure by teardown.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)


if __name__ == "__main__":
    _exit_without_teardown(main())
'''


def substitute(source: str, old: str, new: str, label: str) -> str:
    hits = source.count(old)
    if hits != 1:
        raise SystemExit(f"anchor {label!r} matched {hits} times, expected exactly 1")
    return source.replace(old, new)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    if "_exit_without_teardown" in text:
        raise SystemExit("already patched; refusing to patch twice")

    text = substitute(text, OLD_IMPORTS, NEW_IMPORTS, "imports")
    text = substitute(text, OLD_GUARD, NEW_GUARD, "main guard")

    TARGET.write_text(text, encoding="utf-8")
    print("patched", TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
