"""Cut a readable window out of a retrieved runner log and annotate it.

Runner logs prefix every line with "job<TAB>step<TAB>timestamp ". That prefix
is bookkeeping, not program output, so it is stripped before anything is
published.

The window is cut around the first error marker rather than around the end of
the file. The end of a runner log is always the post-job git teardown and
never carries the diagnosis.

Read-only. Takes run ids on argv and expects forensics/<run>.redacted.log to
already exist.
"""

import re
import sys
from pathlib import Path

PREFIX = re.compile(r"^[^\t]*\t[^\t]*\t\S+Z ")
MARKERS = (
    "##[error]",
    "Traceback (most recent call last)",
    "AssertionError",
    "[FAIL]",
    "Error:",
    "FAILED",
    "Exception",
)


def main(runs):
    for run in runs:
        path = Path(f"forensics/{run}.redacted.log")
        if not path.exists():
            print(f"::warning title=missing::no redacted log for {run}")
            continue

        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
        lines = [PREFIX.sub("", line).rstrip() for line in raw]
        lines = [line for line in lines if line.strip()]

        hits = [i for i, line in enumerate(lines) if any(m in line for m in MARKERS)]
        print(f"::group::run {run}: {len(lines)} non-empty lines, {len(hits)} marker lines")
        if hits:
            window = lines[max(0, hits[0] - 60):min(len(lines), hits[-1] + 8)]
        else:
            window = lines[-100:]
        for line in window:
            print(line)
        print("::endgroup::")

        excerpt = " ~ ".join(window)[-1700:]
        title = f"failure site {run}" if hits else f"no error marker in {run}"
        print(f"::error title={title}::{excerpt}")

        Path(f"forensics/{run}.window.txt").write_text("\n".join(window), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
