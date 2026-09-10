"""Deterministic stand-in for the native teardown abort described in #68.

Nothing here reproduces the *cause* of that abort. It reproduces its
*shape*, on demand, at exactly the same point in the process lifetime, so
that a guard against it can be proven rather than asserted.

What the real failure looks like (retrieved from the logs of runs
33964738277, 33982259880 and 34027310847):

    RESULT: PASS
    terminate called without an active exception
    step failed: <step> (exit -6)

The child finished all its work, printed its own PASS block, `main()`
returned 0, and the process then died with SIGABRT while shutting down.
That message comes from the C++ runtime, not from Python: a `std::thread`
was destroyed while still joinable, during the static-destructor phase that
CPython triggers after the interpreter has finalised.

That phase is unreachable from Python, so it cannot be hooked directly.
`atexit` is the closest observable equivalent: it runs after the program's
work is complete, on the normal-exit path, and it is skipped by exactly the
same mechanism (`os._exit`) that skips the native destructors. Aborting from
an `atexit` hook therefore produces the identical outcome, exit 134/SIGABRT
after a successful run, through the identical decision point.

Enabled only when INJECT_TEARDOWN_ABORT=1 is set in the environment, and only
loaded when this directory is on PYTHONPATH. It is inert everywhere else.
"""

import os

if os.environ.get("INJECT_TEARDOWN_ABORT") == "1":
    import atexit
    import sys

    def _abort_during_teardown() -> None:
        # Announce it first: an abort with no explanation in the log is how
        # this class of failure stayed unexplained for three issues.
        sys.stderr.write("injected: aborting during interpreter teardown\n")
        sys.stderr.flush()
        os.abort()

    atexit.register(_abort_during_teardown)
