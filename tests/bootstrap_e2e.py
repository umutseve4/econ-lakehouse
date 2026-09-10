"""Cold-start bootstrap end-to-end check (fixture mode, real pipeline).

Previously inlined as a heredoc in pipeline.yml's dashboard-smoke job. It was
moved into a file so .github/scripts/step-with-forensics.sh can wrap it: that
wrapper runs its argv directly and cannot execute a heredoc.

Asserts that a clean checkout with no warehouse builds one in fixture mode,
and that the provenance record agrees with what the bootstrap reports. The
two must be checked together. A bootstrap that returns "built-fixture" while
writing a provenance file saying something else is precisely the kind of
disagreement that makes a later live/fixture mix-up unfalsifiable.
"""

import json
import sys
from pathlib import Path

# Run as a file, sys.path[0] is tests/, not the repository root. The heredoc
# form got the root for free because sys.path[0] was ''. Restore it, or the
# dashboard import below fails before anything is actually tested.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.bootstrap import ensure_warehouse  # noqa: E402


def main() -> int:
    mode = ensure_warehouse()
    provenance = json.loads(Path("warehouse/provenance.json").read_text())

    print("===== OTOMATIK KONTROL =====")
    print("bootstrap_mode:", mode)
    print("provenance_mode:", provenance.get("mode"))
    print("provenance_source:", provenance.get("source_name"))

    ok = mode == "built-fixture" and provenance.get("mode") == "fixture"
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
