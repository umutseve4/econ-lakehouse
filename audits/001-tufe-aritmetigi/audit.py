#!/usr/bin/env python3
"""Denetim 001. TUFE ic aritmetik tutarliligi ve yeniden uretilebilirlik.

Protokol: audits/001-tufe-aritmetigi/PROTOCOL.md (sonuclardan ONCE commit edildi)

Bu betik raporda gecen HER sayiyi ham CSV'den yeniden hesaplar ve
README.md icinde ilan edilen degerlerle karsilastirir. Bir sayi tutmazsa
cikis kodu 1 doner. Yani rapor CI tarafindan surekli yeniden dogrulanir.

Kullanim:
    python audits/001-tufe-aritmetigi/audit.py            # rapor bas
    python audits/001-tufe-aritmetigi/audit.py --check    # ilan edilenle karsilastir
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys
from decimal import Decimal as D
from decimal import getcontext

getcontext().prec = 50

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data"

# Yuvarlama yaricapi. Yayimlanan tum sayilar iki ondalikli.
H = D("0.005")

# Yayimlanan yillik oranlar, Agustos 2026.
TUIK_YOY = D("31.51")   # kaynak T3
ENAG_YOY = D("49.03")   # kaynak E1, bagimsiz teyit E3

# PROTOCOL.md bolum 3'te ilan edilen degerler. Bunlar CI'in koruma cengelidir.
BEYAN = {
    "A_ay_sayisi": 64,
    "A_fail": 0,
    "A_en_buyuk_artik": "0.004978",
    "B_tuik_bilesik": "31.491938",
    "B_tuik_fark": "-0.018062",
    "B_enag_bilesik": "49.046410",
    "B_enag_fark": "0.016410",
    "C_sentetik_endeks": "4288.77",
    "C_carpan": "8.9872",
    "C_yuz_tl": "898.72",
    "C_kurus": "11.13",
    "D_tuik": "8/8",
    "D_enag": "2/8",
}


def q(x: D, n: str) -> str:
    return str(x.quantize(D(n)))


def oku_tuik():
    with (DATA / "tuik_tufe.csv").open() as fh:
        return list(csv.DictReader(fh))


def oku_enag():
    with (DATA / "enag_etufe.csv").open() as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------- KATMAN A
def katman_a(rows):
    """Endeks duzeyi ile yayimlanan aylik oran birbirini tutuyor mu.

    Tolerans SABIT DEGILDIR. Hem endeks hem oran iki ondaliga yuvarlidir;
    endeksten dogan hata endeksin buyuklugune gore degisir. Bu yuzden
    her ay icin tam alt/ust sinir ayri hesaplanir. Bkz. PROTOCOL.md bolum 2.
    """
    lv = [r for r in rows if r["endeks_2003_100"]]
    satirlar, fail = [], 0
    for onceki, simdi in zip(lv, lv[1:]):
        a, b = D(simdi["endeks_2003_100"]), D(onceki["endeks_2003_100"])
        pub = D(simdi["aylik_degisim_yuzde"])
        implied = (a / b - D(1)) * 100
        alt = ((a - H) / (b + H) - D(1)) * 100 - H
        ust = ((a + H) / (b - H) - D(1)) * 100 + H
        gecti = alt <= pub <= ust
        fail += 0 if gecti else 1
        satirlar.append(
            {
                "ay": simdi["ay"],
                "yayimlanan": str(pub),
                "endeksten": q(implied, "0.000001"),
                "artik_pp": q(implied - pub, "0.000001"),
                "tolerans_alt": q(alt, "0.000001"),
                "tolerans_ust": q(ust, "0.000001"),
                "gecti": gecti,
            }
        )
    artiklar = [abs(D(s["artik_pp"])) for s in satirlar]
    yaricap = [(D(s["tolerans_ust"]) - D(s["tolerans_alt"])) / 2 for s in satirlar]
    return {
        "ay_sayisi": len(satirlar),
        "fail": fail,
        "en_buyuk_artik": q(max(artiklar), "0.000001"),
        "ortalama_artik": q(sum(artiklar) / len(artiklar), "0.000001"),
        "tolerans_yaricap_min": q(min(yaricap), "0.000001"),
        "tolerans_yaricap_max": q(max(yaricap), "0.000001"),
        "satirlar": satirlar,
    }


# --------------------------------------------------------------- KATMAN B
def katman_b(oranlar, yayimlanan_yillik, ad):
    """12 aylik bilesik, yayimlanan yillik oranla uyumlu mu.

    UYARI, PROTOCOL.md bolum 4/1: bu bir OZDESLIK kontroludur. Yillik oran
    ayni endeksten turedigi icin ara terimler sadelesir. Kopyalama ve
    zincirleme hatasini yakalar; olculen enflasyonun DOGRULUGUNU sinamaz.
    """
    if len(oranlar) != 12:
        raise ValueError(f"{ad}: 12 ay bekleniyordu, {len(oranlar)} geldi")
    nom = lo = hi = D(1)
    for r in oranlar:
        r = D(r)
        nom *= D(1) + r / 100
        lo *= D(1) + (r - H) / 100
        hi *= D(1) + (r + H) / 100
    nom, lo, hi = ((x - D(1)) * 100 for x in (nom, lo, hi))
    lo -= H  # yayimlanan yillik oranin kendi yuvarlamasi
    hi += H
    fark = nom - yayimlanan_yillik
    return {
        "kurum": ad,
        "bilesik": q(nom, "0.000001"),
        "yayimlanan": str(yayimlanan_yillik),
        "fark_pp": q(fark, "0.000001"),
        "zarf_alt": q(lo, "0.000001"),
        "zarf_ust": q(hi, "0.000001"),
        "zarf_kullanim_yuzde": q(abs(fark) / max(hi - nom, nom - lo) * 100, "0.1"),
        "uyumlu": lo <= yayimlanan_yillik <= hi,
    }


# --------------------------------------------------------------- KATMAN C
def katman_c(rows):
    """Kumulatif fiyat duzeyi.

    UYARI, PROTOCOL.md bolum 4/4: Agustos 2026 icin uretilen 2003=100
    degeri SENTETIKTIR. TUIK boyle bir sayi yayimlamiyor; Ocak 2026'dan
    itibaren resmi seri 2025=100 (kaynak T4, T5). Deger, Aralik 2025 resmi
    endeksinden yayimlanan sekiz aylik oranla zincirlenmistir.
    """
    son_resmi = [r for r in rows if r["endeks_2003_100"]][-1]
    lv = lo = hi = D(son_resmi["endeks_2003_100"])
    zincir = [r for r in rows if not r["endeks_2003_100"]]
    for r in zincir:
        x = D(r["aylik_degisim_yuzde"])
        lv *= D(1) + x / 100
        lo *= D(1) + (x - H) / 100
        hi *= D(1) + (x + H) / 100
    baz = D(next(r for r in rows if r["ay"] == "2020-09")["endeks_2003_100"])
    return {
        "son_resmi_ay": son_resmi["ay"],
        "son_resmi_endeks": son_resmi["endeks_2003_100"],
        "zincirlenen_ay": len(zincir),
        "sentetik_endeks": q(lv, "0.01"),
        "sentetik_band": [q(lo, "0.01"), q(hi, "0.01")],
        "baz_ay": "2020-09",
        "baz_endeks": str(baz),
        "carpan": q(lv / baz, "0.0001"),
        "carpan_band": [q(lo / baz, "0.0001"), q(hi / baz, "0.0001")],
        "kumulatif_artis_yuzde": q((lv / baz - D(1)) * 100, "0.01"),
        "yuz_tl_bugun": q(100 * lv / baz, "0.01"),
        "bir_tl_kurus": q(100 * baz / lv, "0.01"),
        "zincir_adimi_ay": 71,
        "gozlem_etiketi_ay": 72,
    }


# --------------------------------------------------------------- KATMAN D
OLCUTLER = [
    ("Resmi bulten, tarih ve sayi numarali", True, False),
    ("Endeks DUZEYI yayimlaniyor, sadece oran degil", True, False),
    ("Tam tarihsel seri tek kaynaktan derlenebiliyor", True, False),
    ("Makine-okunur seri (CSV / XLSX / API)", True, False),
    ("Ayrintili metodoloji belgesi kamuya acik", True, False),
    ("Sepet madde sayisi ve agirliklari yayimlaniyor", True, False),
    ("12 aylik ozdeslik testi UYGULANABILDI", True, True),
    ("12 aylik ozdeslik testini GECTI", True, True),
]


def katman_d():
    t = sum(1 for _, a, _ in OLCUTLER if a)
    e = sum(1 for _, _, b in OLCUTLER if b)
    return {
        "tuik": f"{t}/{len(OLCUTLER)}",
        "enag": f"{e}/{len(OLCUTLER)}",
        "olcutler": [
            {"olcut": c, "tuik": a, "enag": b} for c, a, b in OLCUTLER
        ],
    }


def main() -> int:
    trows = oku_tuik()
    erows = oku_enag()

    a = katman_a(trows)
    pencere = [r["aylik_degisim_yuzde"] for r in trows if r["ay"] >= "2025-09"]
    b_t = katman_b(pencere, TUIK_YOY, "TUIK")
    b_e = katman_b([r["aylik_degisim_yuzde"] for r in erows], ENAG_YOY, "ENAG")
    c = katman_c(trows)
    d = katman_d()

    print("KATMAN A  TUIK endeks duzeyi <-> aylik oran")
    print(f"  incelenen ay        : {a['ay_sayisi']}")
    print(f"  toleransi asan ay   : {a['fail']}")
    print(f"  en buyuk artik      : {a['en_buyuk_artik']} pp")
    print(f"  tolerans yaricapi   : {a['tolerans_yaricap_min']} .. "
          f"{a['tolerans_yaricap_max']} pp (aya gore degisir)")

    print("\nKATMAN B  12 aylik ozdeslik testi, ayni test iki kuruma")
    for r in (b_t, b_e):
        print(f"  {r['kurum']:<5} bilesik={r['bilesik']}%  "
              f"yayim={r['yayimlanan']}%  fark={r['fark_pp']}pp  "
              f"zarf=[{r['zarf_alt']},{r['zarf_ust']}]  "
              f"kullanim=%{r['zarf_kullanim_yuzde']}  "
              f"{'UYUMLU' if r['uyumlu'] else 'UYUMSUZ'}")

    print("\nKATMAN C  kumulatif fiyat duzeyi (SENTETIK seri)")
    print(f"  Agustos 2026 sentetik 2003=100 : {c['sentetik_endeks']} "
          f"band {c['sentetik_band']}")
    print(f"  Eylul 2020 -> Agustos 2026     : x{c['carpan']} "
          f"(+{c['kumulatif_artis_yuzde']}%)")
    print(f"  100 TL -> {c['yuz_tl_bugun']} TL,  1 TL -> {c['bir_tl_kurus']} kurus")

    print("\nKATMAN D  yeniden uretilebilirlik karnesi")
    print(f"  {'olcut':<50}{'TUIK':>7}{'ENAG':>7}")
    for o in d["olcutler"]:
        print(f"  {o['olcut']:<50}"
              f"{('EVET' if o['tuik'] else 'HAYIR'):>7}"
              f"{('EVET' if o['enag'] else 'HAYIR'):>7}")
    print(f"  {'TOPLAM':<50}{d['tuik']:>7}{d['enag']:>7}")

    sonuc = {"katman_A": a, "katman_B": [b_t, b_e], "katman_C": c, "katman_D": d}
    (HERE / "results.json").write_text(json.dumps(sonuc, indent=1, ensure_ascii=False))

    if "--check" not in sys.argv:
        return 0

    gercek = {
        "A_ay_sayisi": a["ay_sayisi"],
        "A_fail": a["fail"],
        "A_en_buyuk_artik": a["en_buyuk_artik"],
        "B_tuik_bilesik": b_t["bilesik"],
        "B_tuik_fark": b_t["fark_pp"],
        "B_enag_bilesik": b_e["bilesik"],
        "B_enag_fark": b_e["fark_pp"],
        "C_sentetik_endeks": c["sentetik_endeks"],
        "C_carpan": c["carpan"],
        "C_yuz_tl": c["yuz_tl_bugun"],
        "C_kurus": c["bir_tl_kurus"],
        "D_tuik": d["tuik"],
        "D_enag": d["enag"],
    }
    kotu = {k: (v, gercek[k]) for k, v in BEYAN.items() if str(v) != str(gercek[k])}

    print("\n--- BEYAN KONTROLU ---")
    if kotu:
        for k, (beklenen, bulunan) in kotu.items():
            print(f"  SAPMA {k}: raporda '{beklenen}', hesapta '{bulunan}'")
        print(f"  {len(kotu)} sapma. Rapordaki sayilar veriyle uyusmuyor.")
        return 1

    # protokoldeki PASS/FAIL esikleri
    if a["fail"] != 0:
        print(f"  KATMAN A FAIL: {a['fail']} ay tolerans disinda")
        return 1
    for r in (b_t, b_e):
        if not r["uyumlu"]:
            print(f"  KATMAN B FAIL: {r['kurum']} zarf disinda")
            return 1

    print(f"  {len(BEYAN)} beyanin tamami veriyle uyusuyor.")
    print("  Katman A ve B, PROTOCOL.md bolum 3 esiklerini geciyor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
