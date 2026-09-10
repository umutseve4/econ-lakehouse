"""Kok README.md icine Denetim 001 bolumunu tek seferlik ekler.

Neden betik: README buyuk bir dosya. Elle yeniden yazmak bayt duzeyinde
bozulma riski tasir. Bu betik dosyanin geri kalanina hic dokunmaz, yalnizca
capanin onune bir blok ekler.

Emniyet: capa tam bir kez eslesmezse ya da bolum zaten varsa cikis kodu 1.
"""
from __future__ import annotations

import pathlib
import sys

CAPA = "---\n\n## Run the whole thing in four commands"
BLOK = pathlib.Path(".github/one-shot/denetim-001-blok.md")
HEDEF = pathlib.Path("README.md")
IMZA = "## Audit 001: is the Turkish CPI gap an arithmetic error?"


def main() -> int:
    t = HEDEF.read_text(encoding="utf-8")

    if IMZA in t:
        print("HATA: bolum zaten var, yama ikinci kez uygulanmak uzereydi")
        return 1

    hits = t.count(CAPA)
    if hits != 1:
        print("HATA: capa %d kez bulundu, tam 1 bekleniyordu" % hits)
        return 1

    blok = BLOK.read_text(encoding="utf-8")
    if IMZA not in blok:
        print("HATA: blok dosyasi beklenen basligi icermiyor")
        return 1

    yeni = t.replace(CAPA, blok + CAPA, 1)

    # Capa metni korunmali, yalnizca onune ekleme yapilmali.
    if yeni.count(CAPA) != 1 or len(yeni) != len(t) + len(blok):
        print("HATA: yama beklenen sonucu uretmedi")
        return 1

    HEDEF.write_text(yeni, encoding="utf-8")
    print("yama uygulandi, %d bayt eklendi" % len(blok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
