#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Bir CI adimini calistirir; adim duserse, dusme nedenini ham logdan cikarip
# GitHub *annotation* olarak yayinlar.
#
# Neden bu var:
#   #60, #63, #68 ve #70'in dordunun de tikandigi yer ayni: elde yalnizca
#   "Process completed with exit code 1" annotation'i vardi ve gercek geri
#   izleme yalnizca oturum acilmis bir tarayicidan okunabilen ham logdaydi.
#   Bir hatayi goremeden duzeltmeye calismak, duzeltmenin ise yarayip
#   yaramadigini asla bilememek demektir (#68).
#
#   Annotation'lar ham logun aksine API'den okunabilir. Bu sarmalayici,
#   komutun ciktisini bir dosyaya alir, adim duserse son satirlari tek bir
#   cok satirli ::error:: annotation'ina kodlar ve calisma alaninin durumunu
#   dokerek artifact'e birakir.
#
# Sozlesme:
#   - Cikis kodu HER ZAMAN oldugu gibi iletilir. Bu betik hicbir hatayi
#     yutmaz, yumusatmaz veya yeniden denemez; yalnizca gorunur kilar.
#   - Teshis kodunun kendisi adimi dusuremez veya gecirmez.
#
# Kullanim: bash .github/scripts/step-with-forensics.sh <etiket> <komut...>
# ---------------------------------------------------------------------------
set -uo pipefail

if [ "$#" -lt 2 ]; then
  echo "kullanim: step-with-forensics.sh <etiket> <komut...>" >&2
  exit 2
fi

label="$1"
shift

mkdir -p artifacts
log="artifacts/${label}.log"

echo "+ $*"
"$@" >"$log" 2>&1
code=$?

# Ciktiyi her durumda job loguna da bas: basarili kosularin taban cizgisi
# olmadan basarisiz kosunun ciktisi yorumlanamaz.
cat "$log"

if [ "$code" -eq 0 ]; then
  echo "${label}: OK"
  exit 0
fi

echo "::group::adli kanit — ${label} (exit ${code})"
echo "--- warehouse/ ---"
ls -la warehouse 2>/dev/null || echo "(warehouse/ yok)"
echo "--- warehouse/run_log_parts/ (son 20) ---"
ls -la warehouse/run_log_parts 2>/dev/null | tail -n 20 || echo "(run_log_parts/ yok)"
echo "--- kilit dosyalari ---"
ls -la warehouse/.run_log.parquet.lock 2>/dev/null || echo "(kilit dosyasi yok)"
echo "--- dbt loglari (son 40 satir) ---"
tail -n 40 logs/dbt.log 2>/dev/null || tail -n 40 target/dbt.log 2>/dev/null || echo "(dbt logu yok)"
echo "--- cozulen veri yigini ---"
cat artifacts/datastack.txt 2>/dev/null || echo "(envanter yakalanmadi)"
echo "--- disk ---"
df -h . 2>/dev/null || true
echo "::endgroup::"

# Son satirlari tek bir cok satirli annotation'a kodla. GitHub annotation
# govdesinde ham satir sonu kabul etmez; %0A ile kacislanir ve % kendisi
# once kacislanmalidir, yoksa metindeki bir "%0A" dizisi bozulur.
python3 - "$log" "$label" "$code" <<'PY' || echo "::error title=${label}::adim exit ${code} ile dustu (teshis kodlayici calismadi)"
import sys

log_path, label, code = sys.argv[1], sys.argv[2], sys.argv[3]

try:
    with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
        lines = handle.read().splitlines()
except OSError as exc:
    print(f"::error title={label}::exit {code}; log okunamadi: {exc!r}")
    raise SystemExit(0)

if not lines:
    print(
        f"::error title={label}::exit {code}; komut hicbir cikti uretmeden "
        f"oldu. Bu, ic bir hata degil dis bir kesinti (sinyal, ortam, disk) "
        f"lehine kanittir — #70'teki B dali."
    )
    raise SystemExit(0)

tail = lines[-40:]
body = "\n".join(tail)
# Annotation govdesi icin guvenli bir ust sinir; GitHub daha uzunlarini keser.
if len(body) > 3000:
    body = "…(kirpildi)…\n" + body[-3000:]

encoded = body.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
print(f"::error title={label} exit {code}::{encoded}")

# Ikinci, dar bir sinyal: son geri izleme satiri genelde tek basina teshis eder.
exc_line = next(
    (ln for ln in reversed(tail) if ln and not ln.startswith((" ", "\t"))),
    "",
)
if exc_line:
    narrow = exc_line[:500].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error title={label} son satir::{narrow}")
PY

exit $code
