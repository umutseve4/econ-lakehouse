"""Denetim 002 testleri.

Denetim 001'in test sekli korunmustur: sabitlenmis uyari cumleleri, uzun tire
yasagi, bir mutasyon testi ve git gecmisinden ön kayit sirasini dogrulayan bir
test. 002'ye ozel olarak, durdurma kurali 1'in kodda gercekten uygulandigini
yapisal olarak dogrulayan testler eklenmistir.
"""

import csv
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DENETIM = os.path.join(KOK, "audits", "002-agirlik-siniri")
AUDIT_PY = os.path.join(DENETIM, "audit.py")
CSV_YOLU = os.path.join(DENETIM, "data", "tuik-2026-08-ana-gruplar.csv")
PROTOKOL = os.path.join(DENETIM, "PROTOCOL.md")
RAPOR = os.path.join(DENETIM, "README.md")
KAYNAKLAR = os.path.join(DENETIM, "data", "SOURCES.md")


def _modul(yol=AUDIT_PY, ad="audit002"):
    spec = importlib.util.spec_from_file_location(ad, yol)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def audit():
    return _modul()


@pytest.fixture(scope="module")
def sonuc(audit):
    return audit.calistir()


# --------------------------------------------------------------------------
# Dosyalarin varligi
# --------------------------------------------------------------------------


@pytest.mark.parametrize("yol", [AUDIT_PY, CSV_YOLU, PROTOKOL, RAPOR, KAYNAKLAR])
def test_dosya_var(yol):
    assert os.path.exists(yol), "eksik dosya: %s" % yol


# --------------------------------------------------------------------------
# Veri butunlugu
# --------------------------------------------------------------------------


def test_on_uc_grup_var(audit):
    assert len(audit.veriyi_oku()) == 13


def test_hicbir_hucre_bos_degil():
    with open(CSV_YOLU, encoding="utf-8", newline="") as f:
        satirlar = list(csv.DictReader(f))
    for s in satirlar:
        for alan in ("grup", "agirlik", "yillik_oran", "yillik_katki", "kaynak"):
            assert (s.get(alan) or "").strip(), "bos hucre: %s / %s" % (
                s.get("grup"),
                alan,
            )


def test_agirlik_toplami_yuvarlama_payinin_icinde(audit, sonuc):
    k2 = sonuc["durdurma_kurali_2"]
    assert k2["atesledi"] is False
    assert abs(k2["sapma"]) <= k2["yuvarlama_payi"]


def test_agirliklar_negatif_degil(audit):
    for s in audit.veriyi_oku():
        assert s["agirlik"] > 0


# --------------------------------------------------------------------------
# Katman A ve durdurma kurali 1
# --------------------------------------------------------------------------


def test_katman_a_kirildi(sonuc):
    assert sonuc["katman_a"]["sonuc"] == "KIRILDI"
    assert sonuc["katman_a"]["zarf_icinde"] is False


def test_artik_zarfin_disinda_ve_uzakta(sonuc):
    a = sonuc["katman_a"]
    assert abs(a["artik"]) > a["zarf_yari_genislik"]
    # Yuvarlamayla aciklanamayacak kadar uzak oldugu iddia ediliyor.
    assert a["artik_zarf_kati"] > 10


def test_durdurma_kurali_1_atesledi(sonuc):
    assert sonuc["durdurma_kurali_1"]["atesledi"] is True
    assert sonuc["durdurma_kurali_1"]["yayimlanmayan"] == ["katman_b", "katman_c"]


def test_katman_b_ve_c_kodda_yok(audit):
    """Durdurma kurali 1 iddia degil, yapi olmali.

    Katman B ve C hesaplanmadi deniyorsa bu fonksiyonlar dosyada bulunmamali.
    """
    assert not hasattr(audit, "katman_b")
    assert not hasattr(audit, "katman_c")
    kaynak = open(AUDIT_PY, encoding="utf-8").read()
    assert "def katman_b" not in kaynak
    assert "def katman_c" not in kaynak


def test_sonucta_katman_b_veya_c_anahtari_yok(sonuc):
    assert "katman_b" not in sonuc
    assert "katman_c" not in sonuc


def test_enag_orani_uzerine_hesap_kurulmamis(audit, sonuc):
    """ENAG orani bu turda yalnizca baglam sabiti; hicbir sonuca girmemeli."""
    duz = json.dumps(sonuc, ensure_ascii=False)
    assert str(audit.ENAG_YILLIK) not in duz


def test_katman_a_kurum_ozel_dal_icermiyor(audit):
    """Denetim 001'deki simetri testinin ayni sekli."""
    kaynak = inspect.getsource(audit.katman_a)
    for yasak in ("TUIK", "ENAG", "tuik", "enag"):
        assert yasak not in kaynak, "katman_a icinde kuruma ozel dal: %s" % yasak


# --------------------------------------------------------------------------
# Tani notu protokol disi olarak isaretli mi
# --------------------------------------------------------------------------


def test_tani_notu_protokol_disi_isaretli(sonuc):
    assert "tani_notu_protokol_disi" in sonuc


def test_tani_notu_docstringi_uyari_iceriyor(audit):
    d = inspect.getdoc(audit.tani_notu) or ""
    assert "PROTOKOL DISI" in d
    assert "onaylayici kanit degildir" in d


def test_katkilar_mansete_toplaniyor(sonuc):
    t = sonuc["tani_notu_protokol_disi"]
    assert abs(t["katki_artigi"]) < 1e-9


# --------------------------------------------------------------------------
# Beyan kontrolu ve mutasyon
# --------------------------------------------------------------------------


def test_check_temiz_gecer():
    p = subprocess.run(
        [sys.executable, AUDIT_PY, "--check"], capture_output=True, text=True
    )
    assert p.returncode == 0, p.stdout + p.stderr


def test_beyanda_yirmi_bir_deger_var(audit):
    assert len(audit.BEYAN) == 21


@pytest.mark.parametrize(
    "eski,yeni",
    [
        ("24.44,33.79", "24.44,33.80"),  # bir oran bozulur
        ("7.90,13.16", "7.95,13.16"),  # bir agirlik bozulur
        ("2.02,53.44,1.14", "2.02,53.44,1.20"),  # bir katki bozulur
    ],
)
def test_mutasyon_kontrolu_kirar(eski, yeni):
    """Veri bozulursa --check cikis kodu 1 vermeli.

    Koruma yoksa bu test gecmez, yani korumanin varligi iddia degil kanittir.
    """
    with tempfile.TemporaryDirectory() as gecici:
        hedef = os.path.join(gecici, "002")
        shutil.copytree(DENETIM, hedef)
        csv_hedef = os.path.join(hedef, "data", "tuik-2026-08-ana-gruplar.csv")
        metin = open(csv_hedef, encoding="utf-8").read()
        assert metin.count(eski) == 1, "mutasyon capasi tam bir kez eslesmeli: %s" % eski
        open(csv_hedef, "w", encoding="utf-8").write(metin.replace(eski, yeni))
        p = subprocess.run(
            [sys.executable, os.path.join(hedef, "audit.py"), "--check"],
            capture_output=True,
            text=True,
        )
        assert p.returncode == 1, "bozuk veriyle kontrol gecti: " + p.stdout


def test_eksik_hucre_durdurma_kurali_3_atesler():
    with tempfile.TemporaryDirectory() as gecici:
        hedef = os.path.join(gecici, "002")
        shutil.copytree(DENETIM, hedef)
        csv_hedef = os.path.join(hedef, "data", "tuik-2026-08-ana-gruplar.csv")
        metin = open(csv_hedef, encoding="utf-8").read()
        open(csv_hedef, "w", encoding="utf-8").write(
            metin.replace("Saglik,2.79,43.46,1.31", "Saglik,2.79,bulunamadi,1.31")
        )
        p = subprocess.run(
            [sys.executable, os.path.join(hedef, "audit.py"), "--check"],
            capture_output=True,
            text=True,
        )
        assert p.returncode != 0
        assert "DURDURMA KURALI 3" in (p.stdout + p.stderr)


# --------------------------------------------------------------------------
# Rapor metni: sabitlenmis cumleler ve uzun tire yasagi
# --------------------------------------------------------------------------


SABIT_CUMLELER = [
    "Denetim durdu, çünkü kendi hipotezim yanlış çıktı.",
    "Bu bir TÜİK hatası değildir.",
    "Bu bölüm sonuç görüldükten sonra eklenmiştir ve hiçbir hipotezi",
    "H1'in yanlış kurulmuş olması benim hatamdır, TÜİK'in değil.",
    "Ön kayıtta sorulan soru cevapsız kaldı ve **değiştirilmedi**.",
]


@pytest.mark.parametrize("cumle", SABIT_CUMLELER)
def test_rapor_sabit_cumleyi_koruyor(cumle):
    metin = open(RAPOR, encoding="utf-8").read()
    assert cumle in metin, "rapordan silinen sabit cumle: " + cumle


def test_rapor_ikincil_kaynak_uyarisini_iceriyor():
    metin = open(RAPOR, encoding="utf-8").read()
    assert "ikincil" in metin.lower()
    assert "Kendi zaafları" in metin


@pytest.mark.parametrize("yol", [RAPOR, PROTOKOL, KAYNAKLAR, AUDIT_PY])
def test_uzun_tire_yok(yol):
    metin = open(yol, encoding="utf-8").read()
    for karakter, ad in (("\u2014", "em dash"), ("\u2013", "en dash")):
        assert karakter not in metin, "%s icinde %s var" % (yol, ad)


def test_rapor_katman_b_yayimlanmadigini_soyluyor():
    """Durdurma kurali 1 isledi ise rapor bunu acikca yazmali."""
    metin = " ".join(open(RAPOR, encoding="utf-8").read().split())
    assert "Katman B ve Katman C hesaplanmadı ve yayımlanmadı" in metin
    assert "H2 yalanlandı" not in metin
    assert "H2 yalanlanmıştır" not in metin


def test_rapor_ile_sonuc_ayni_sayilari_soyluyor(sonuc):
    """Rapordaki anahtar sayilar hesaplanan degerlerle birebir olmali."""
    metin = open(RAPOR, encoding="utf-8").read()
    a = sonuc["katman_a"]
    beklenen = [
        "%.6f" % a["hesaplanan"],  # 31.278154
        "%.6f" % abs(a["artik"]),  # 0.231846
        "%.2f" % a["artik_zarf_kati"],  # 15.29
        "%.6f" % a["sinira_uzaklik"],  # 0.216682
    ]
    for sayi in beklenen:
        # Rapor Turkce ondalik ayirici kullaniyor.
        assert sayi.replace(".", ",") in metin, "raporda eksik sayi: " + sayi


# --------------------------------------------------------------------------
# Git gecmisi: ön kayit sirasi
# --------------------------------------------------------------------------


def _git(*args):
    try:
        return subprocess.run(
            ["git"] + list(args), cwd=KOK, capture_output=True, text=True
        ).stdout.strip()
    except FileNotFoundError:
        return ""


def test_protokol_veriden_once_commit_edilmis():
    """PROTOCOL.md, veri ve sonuc dosyalarindan once commit edilmis olmali."""
    if not _git("rev-parse", "--is-inside-work-tree"):
        pytest.skip("git deposu yok")

    def ilk_commit(yol):
        c = _git("log", "--reverse", "--format=%H", "--", yol)
        return c.splitlines()[0] if c else None

    p = ilk_commit("audits/002-agirlik-siniri/PROTOCOL.md")
    assert p, "PROTOCOL.md git gecmisinde bulunamadi (fetch-depth: 0 gerekli)"

    for yol in (
        "audits/002-agirlik-siniri/data/tuik-2026-08-ana-gruplar.csv",
        "audits/002-agirlik-siniri/audit.py",
        "audits/002-agirlik-siniri/README.md",
    ):
        c = ilk_commit(yol)
        assert c, "git gecmisinde bulunamadi: " + yol
        assert c != p, "%s protokolle AYNI commit'te; ön kayit sirasi kanitlanamaz" % yol
        sira = _git("rev-list", "--count", "%s..%s" % (p, c))
        assert sira and int(sira) > 0, (
            "%s protokolden once veya ondan bagimsiz commit edilmis" % yol
        )


def test_protokol_tek_basina_commit_edilmis():
    if not _git("rev-parse", "--is-inside-work-tree"):
        pytest.skip("git deposu yok")
    c = _git("log", "--reverse", "--format=%H", "--", "audits/002-agirlik-siniri/PROTOCOL.md")
    if not c:
        pytest.skip("gecmis yok")
    ilk = c.splitlines()[0]
    dosyalar = [
        d
        for d in _git("show", "--name-only", "--format=", ilk).splitlines()
        if d.strip()
    ]
    assert dosyalar == ["audits/002-agirlik-siniri/PROTOCOL.md"], (
        "protokol commit'i tek basina degil: %s" % dosyalar
    )
