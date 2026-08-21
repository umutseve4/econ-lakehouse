"""One-shot EVDS request diagnostics (now probing evds3).

Runs several request variants against EVDS and prints, for each:
status, redirect target (if any), content-type, and body head.
The API key is ALWAYS redacted in output. Exit code is always 0 -
this script diagnoses, it never gates CI.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://evds3.tcmb.gov.tr/service/evds/"
QUERY = (
    "series=TP.FG.J0&startDate=01-01-2024&endDate=01-06-2024"
    "&type=json&frequency=5&aggregationTypes=avg&formulas=0"
)
KEY = os.environ.get("EVDS_API_KEY", "")


def redact(text: str) -> str:
    return text.replace(KEY, "***") if KEY else text


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        raise urllib.error.HTTPError(req.full_url, code, f"redirect->{newurl}", headers, fp)


def probe_urllib(name: str, url: str, headers: dict, follow_redirects: bool) -> None:
    try:
        req = urllib.request.Request(url, headers=headers)
        if follow_redirects:
            opener = urllib.request.build_opener()
        else:
            opener = urllib.request.build_opener(NoRedirect)
        with opener.open(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", "?")
            ctype = resp.headers.get("Content-Type", "?")
            final = resp.geturl()
        is_json = "yes"
        try:
            json.loads(body)
        except json.JSONDecodeError:
            is_json = "NO"
        print(
            f"[{name}] status={status} json={is_json} ctype={ctype} "
            f"final_url={redact(final)} body80={redact(body[:80])!r}"
        )
    except urllib.error.HTTPError as exc:
        loc = exc.headers.get("Location", "-") if exc.headers else "-"
        print(f"[{name}] HTTPError status={exc.code} reason={redact(str(exc.reason))} location={redact(loc)}")
    except Exception as exc:  # noqa: BLE001 - diagnostics must not crash
        print(f"[{name}] EXC {type(exc).__name__}: {redact(str(exc))}")


def probe_requests(name: str, url: str, headers: dict) -> None:
    try:
        import requests  # noqa: PLC0415
    except ImportError:
        print(f"[{name}] SKIP - requests not installed")
        return
    try:
        r = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        is_json = "yes"
        try:
            r.json()
        except ValueError:
            is_json = "NO"
        hops = " -> ".join(redact(h.headers.get("Location", "?")) for h in r.history) or "-"
        print(
            f"[{name}] status={r.status_code} json={is_json} "
            f"ctype={r.headers.get('Content-Type', '?')} redirects={hops} "
            f"final_url={redact(r.url)} body80={redact(r.text[:80])!r}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[{name}] EXC {type(exc).__name__}: {redact(str(exc))}")


def main() -> int:
    if not KEY:
        print("EVDS_API_KEY not set - nothing to diagnose.")
        return 0

    url = BASE + QUERY
    url_with_key_param = url + "&key=" + KEY
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    print("===== EVDS DIAGNOSTIC MATRIX =====")
    probe_urllib("A urllib key-header browserUA", url, {"key": KEY, "User-Agent": ua}, True)
    probe_urllib("B urllib key-header defaultUA", url, {"key": KEY}, True)
    probe_urllib("C urllib key-header noredir", url, {"key": KEY, "User-Agent": ua}, False)
    probe_urllib("D urllib key-in-url", url_with_key_param, {"User-Agent": ua}, True)
    probe_requests("E requests key-header", url, {"key": KEY, "User-Agent": ua})
    probe_requests("F requests key-in-url", url_with_key_param, {"User-Agent": ua})
    print("===== END DIAGNOSTIC =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
