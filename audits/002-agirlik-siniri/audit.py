#!/usr/bin/env python3
"""Denetim 002. Agirlik siniri.

Protokol: audits/002-agirlik-siniri/PROTOCOL.md (veri cekilmeden once commit edildi).

Bu betik rapordaki HER sayiyi ham CSV'den yeniden hesaplar. `--check` ile
calistirildiginda yeniden hesaplanan degerler asagidaki BEYAN sozlugundeki
yayimlanmis degerlerden saparsa cikis kodu 1 verir.

Onemli: Katman A bu denetimde KIRILMISTIR. Protokoldeki durdurma kurali 1
geregi Katman B ve Katman C hesaplanmaz ve yayimlanmaz. Bu betik o kurali
kodda uygular; ilgili fonksiyonlar bilerek yoktur.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

BURA = os.path.dirname(os.path.abspath(__file__))
CSV_YOLU = os.path.join(BURA, "data", "tuik-2026-08-ana-gruplar.csv")
SONUC_YOLU = os.path.join(BURA, "results.json")

# Yayimlanan manset degerleri. Kaynak: data/SOURCES.md kod P1.
MANSET_YILLIK = 31.51
MANSET_AYLIK = 1.84
ENAG_YILLIK = 49.03

# Yayimlanan agirlik toplami. Kaynak tablonun toplam satiri.
AGIRLIK_TOPLAMI_YAYIMLANAN = 100.00

# Yuvarlama yari genisligi. Tum hucreler iki ondalikla yayimlanmistir.
H = 0.005

# Raporda gecen her sayi burada beyan edilir. --check bunlari dogrular.
BEYAN = {
    "grup_sayisi": 13,
    "agirlik_toplami": 99.97,
    "agirlik_toplami_sapmasi": -0.03,
    "agirlik_yuvarlama_payi": 0.065,
    "katman_a_hesaplanan": 31.278154,
    "katman_a_yayimlanan": 31.51,
    "katman_a_artik": -0.231846,
    "katman_a_zarf_alt": 31.262992,
    "katman_a_zarf_ust": 31.293318,
    "katman_a_zarf_yari_genislik": 0.015163,
    "katman_a_sinira_uzaklik": 0.216682,
    "katman_a_artik_zarf_kati": 15.29,
    "katman_a_sonuc": "KIRILDI",
    "durdurma_kurali_1": "ATESLENDI",
    "durdurma_kurali_2": "ATESLENMEDI",
    "durdurma_kurali_3": "ATESLENMEDI",
    "katki_toplami": 31.51,
    "katki_artigi": 0.0,
    "en_buyuk_etkin_agirlik_sapmasi_grup": "Giyim ve ayakkabi",
    "en_buyuk_etkin_agirlik_sapmasi": -2.58,
    "etkin_agirlik_toplami": 98.7576,
}


def veriyi_oku(yol=CSV_YOLU):
    with open(yol, encoding="utf-8", newline="") as f:
        satirlar = list(csv.DictReader(f))
    if not satirlar:
        raise SystemExit("veri dosyasi bos: " + yol)
    cikti = []
    for s in satirlar:
        for alan in ("agirlik", "yillik_oran", "yillik_katki"):
            deger = (s.get(alan) or "").strip()
            if deger == "" or deger.lower() == "bulunamadi":
                # Durdurma kurali 3. Eksik kalem gizlenmez.
                raise SystemExit(
                    "DURDURMA KURALI 3: '%s' grubunda '%s' alani eksik."
                    % (s.get("grup", "?"), alan)
                )
            s[alan] = float(deger)
        cikti.append(s)
    return cikti


def durdurma_kurali_2(satirlar):
    """Agirlik toplami yayimlanan toplamdan yuvarlama payindan fazla saparsa dur."""
    toplam = sum(s["agirlik"] for s in satirlar)
    sapma = toplam - AGIRLIK_TOPLAMI_YAYIMLANAN
    pay = len(satirlar) * H
    return {
        "agirlik_toplami": toplam,
        "sapma": sapma,
        "yuvarlama_payi": pay,
        "atesledi": abs(sapma) > pay,
    }


def katman_a(satirlar):
    """Kesit toplulastirma ozdesligi. H1.

    r_hesaplanan = toplam(w_i * r_i) / toplam(w_i)

    Zarf, protokoldeki isaret secimiyle kurulur: ust sinir icin orani
    hesaplanan ortalamanin uzerinde olan gruplara +h_w, altinda olanlara -h_w
    verilir, tum oranlara +h_r eklenir; alt sinir icin tersi. Sonuca ayrica
    h_r eklenir cunku yayimlanan manset de yuvarlanmistir.

    Bu fonksiyonda kuruma ozel hicbir dal yoktur; girdi hangi kurumdan gelirse
    gelsin ayni islem uygulanir.
    """
    W = sum(s["agirlik"] for s in satirlar)
    hesaplanan = sum(s["agirlik"] * s["yillik_oran"] for s in satirlar) / W

    def sinir(ust):
        pay = 0.0
        payda = 0.0
        for s in satirlar:
            ustunde = s["yillik_oran"] > hesaplanan
            if ust:
                isaret = 1 if ustunde else -1
            else:
                isaret = -1 if ustunde else 1
            w = s["agirlik"] + isaret * H
            r = s["yillik_oran"] + (H if ust else -H)
            pay += w * r
            payda += w
        return pay / payda

    zarf_ust = sinir(True) + H
    zarf_alt = sinir(False) - H
    artik = hesaplanan - MANSET_YILLIK
    icinde = zarf_alt <= MANSET_YILLIK <= zarf_ust
    yari = (zarf_ust - zarf_alt) / 2
    return {
        "hesaplanan": hesaplanan,
        "yayimlanan": MANSET_YILLIK,
        "artik": artik,
        "zarf_alt": zarf_alt,
        "zarf_ust": zarf_ust,
        "zarf_yari_genislik": yari,
        "zarf_icinde": icinde,
        "sinira_uzaklik": min(
            abs(MANSET_YILLIK - zarf_alt), abs(MANSET_YILLIK - zarf_ust)
        ),
        "artik_zarf_kati": abs(artik) / yari,
        "sonuc": "UYUMLU" if icinde else "KIRILDI",
    }


def tani_notu(satirlar):
    """PROTOKOL DISI. Sonuc goruldukten SONRA eklenmistir.

    Bu blok bir hipotez testi degildir ve hicbir iddiayi dogrulamaz. Katman A
    neden kirildi sorusuna dair bir gozlemi kayda gecirir: TUIK'in yayimladigi
    yillik katkilar mansete tam olarak toplanmaktadir, dolayisiyla kirilma
    veri aktarim hatasindan degil, H1'in yanlis bir toplulastirma modeli
    olmasindan gelmektedir. Ima edilen etkin agirlik w_eff_i = k_i / r_i * 100
    olarak yazilir. Bu sayilarin gecerliligi katkilarin ayni yuvarlama
    izgarasinda yayimlanmis olmasina baglidir; onaylayici kanit degildir.
    """
    katki_toplami = sum(s["yillik_katki"] for s in satirlar)
    etkin = []
    for s in satirlar:
        we = s["yillik_katki"] / s["yillik_oran"] * 100
        etkin.append(
            {
                "grup": s["grup"],
                "agirlik": s["agirlik"],
                "etkin_agirlik": we,
                "sapma": we - s["agirlik"],
            }
        )
    enb = min(etkin, key=lambda e: e["sapma"])
    return {
        "katki_toplami": katki_toplami,
        "katki_artigi": katki_toplami - MANSET_YILLIK,
        "etkin_agirliklar": etkin,
        "etkin_agirlik_toplami": sum(e["etkin_agirlik"] for e in etkin),
        "en_buyuk_negatif_sapma_grup": enb["grup"],
        "en_buyuk_negatif_sapma": enb["sapma"],
    }


def calistir():
    satirlar = veriyi_oku()
    k2 = durdurma_kurali_2(satirlar)
    a = katman_a(satirlar)

    sonuc = {
        "denetim": "002-agirlik-siniri",
        "donem": "2026-08",
        "grup_sayisi": len(satirlar),
        "durdurma_kurali_2": k2,
        "katman_a": a,
    }

    # Protokol, durdurma kurali 1. Katman A kirilirsa Katman B ve C
    # hesaplanmaz ve yayimlanmaz. Kirik bir ozdesligin ustune kurulan sinir
    # argumani gecersizdir.
    if a["sonuc"] == "KIRILDI":
        sonuc["durdurma_kurali_1"] = {
            "atesledi": True,
            "aciklama": (
                "Katman A zarfin disina cikti. Protokol geregi Katman B "
                "(ulasilabilir aralik) ve Katman C (tek grup tasima yuku) "
                "hesaplanmadi ve yayimlanmadi."
            ),
            "yayimlanmayan": ["katman_b", "katman_c"],
        }
        sonuc["tani_notu_protokol_disi"] = tani_notu(satirlar)
    else:
        raise SystemExit(
            "Katman A uyumlu cikti. Bu kod yolu bu denetimde kullanilmadi; "
            "Katman B ve C ayri bir commit'te eklenmelidir."
        )

    return sonuc


def kontrol(sonuc):
    a = sonuc["katman_a"]
    t = sonuc["tani_notu_protokol_disi"]
    k2 = sonuc["durdurma_kurali_2"]
    gozlenen = {
        "grup_sayisi": sonuc["grup_sayisi"],
        "agirlik_toplami": k2["agirlik_toplami"],
        "agirlik_toplami_sapmasi": k2["sapma"],
        "agirlik_yuvarlama_payi": k2["yuvarlama_payi"],
        "katman_a_hesaplanan": a["hesaplanan"],
        "katman_a_yayimlanan": a["yayimlanan"],
        "katman_a_artik": a["artik"],
        "katman_a_zarf_alt": a["zarf_alt"],
        "katman_a_zarf_ust": a["zarf_ust"],
        "katman_a_zarf_yari_genislik": a["zarf_yari_genislik"],
        "katman_a_sinira_uzaklik": a["sinira_uzaklik"],
        "katman_a_artik_zarf_kati": a["artik_zarf_kati"],
        "katman_a_sonuc": a["sonuc"],
        "durdurma_kurali_1": (
            "ATESLENDI" if sonuc["durdurma_kurali_1"]["atesledi"] else "ATESLENMEDI"
        ),
        "durdurma_kurali_2": "ATESLENDI" if k2["atesledi"] else "ATESLENMEDI",
        "durdurma_kurali_3": "ATESLENMEDI",
        "katki_toplami": t["katki_toplami"],
        "katki_artigi": t["katki_artigi"],
        "en_buyuk_etkin_agirlik_sapmasi_grup": t["en_buyuk_negatif_sapma_grup"],
        "en_buyuk_etkin_agirlik_sapmasi": t["en_buyuk_negatif_sapma"],
        "etkin_agirlik_toplami": t["etkin_agirlik_toplami"],
    }

    hatalar = []
    for anahtar, beklenen in BEYAN.items():
        if anahtar not in gozlenen:
            hatalar.append("BEYAN'da olup hesaplanmayan anahtar: %s" % anahtar)
            continue
        bulunan = gozlenen[anahtar]
        if isinstance(beklenen, str):
            if bulunan != beklenen:
                hatalar.append(
                    "%s: beyan '%s', hesaplanan '%s'" % (anahtar, beklenen, bulunan)
                )
        else:
            # Beyan raporda kac ondalikla yaziliysa o hassasiyette dogrulanir.
            metin = repr(float(beklenen))
            ondalik = len(metin.split(".")[1].rstrip("0")) if "." in metin else 0
            if round(float(bulunan), ondalik) != round(float(beklenen), ondalik):
                hatalar.append(
                    "%s: beyan %s, hesaplanan %.10f" % (anahtar, beklenen, bulunan)
                )
    for eksik in sorted(set(gozlenen) - set(BEYAN)):
        hatalar.append("hesaplanip BEYAN edilmeyen anahtar: %s" % eksik)

    if hatalar:
        print("KONTROL BASARISIZ. Rapordaki beyan ile hesaplama uyusmuyor:")
        for h in hatalar:
            print("  - " + h)
        return 1
    print("KONTROL TAMAM. %d beyan edilen deger ham veriden dogrulandi." % len(BEYAN))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="beyan ile karsilastir")
    ap.add_argument("--json", action="store_true", help="results.json yaz")
    args = ap.parse_args()

    sonuc = calistir()

    if args.json:
        with open(SONUC_YOLU, "w", encoding="utf-8") as f:
            json.dump(sonuc, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        print("yazildi: " + SONUC_YOLU)

    if args.check:
        return kontrol(sonuc)

    if not args.json:
        print(json.dumps(sonuc, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
