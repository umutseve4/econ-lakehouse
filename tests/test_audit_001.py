"""Denetim 001'in raporunda gecen her sayiyi ham CSV'den yeniden dogrular.

Bu dosyanin varlik sebebi: audits/001-tufe-aritmetigi/README.md statik metin
degil, dogrulanan bir iddia olsun. Rapordaki bir sayi degistirilir ama veri
degistirilmezse (ya da tersi) bu testler kirilir.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "audits" / "001-tufe-aritmetigi"
AUDIT_PY = AUDIT_DIR / "audit.py"


def _load():
    spec = importlib.util.spec_from_file_location("audit_001", AUDIT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _load()


@pytest.fixture(scope="module")
def res(m):
    trows, erows = m.oku_tuik(), m.oku_enag()
    pencere = [r["aylik_degisim_yuzde"] for r in trows if r["ay"] >= "2025-09"]
    return {
        "A": m.katman_a(trows),
        "Bt": m.katman_b(pencere, m.TUIK_YOY, "TUIK"),
        "Be": m.katman_b([r["aylik_degisim_yuzde"] for r in erows], m.ENAG_YOY, "ENAG"),
        "C": m.katman_c(trows),
        "D": m.katman_d(),
    }


# ---------------------------------------------------------------- veri butunlugu
def test_tuik_csv_satir_sayisi(m):
    rows = m.oku_tuik()
    assert len(rows) == 73, "2020-08 baz satiri + 72 gozlem bekleniyor"
    assert sum(1 for r in rows if r["endeks_2003_100"]) == 65
    assert rows[0]["ay"] == "2020-08" and rows[-1]["ay"] == "2026-08"


def test_enag_csv_tam_12_ay(m):
    rows = m.oku_enag()
    assert len(rows) == 12
    assert rows[0]["ay"] == "2025-09" and rows[-1]["ay"] == "2026-08"
    assert all(r["aylik_degisim_yuzde"] and r["kaynak"] for r in rows), \
        "her ENAG satiri bir kaynak koduna bagli olmali"


def test_her_kaynak_kodu_sources_md_de_tanimli(m):
    txt = (AUDIT_DIR / "data" / "SOURCES.md").read_text(encoding="utf-8")
    kodlar = set()
    for r in m.oku_tuik():
        kodlar |= {r["endeks_kaynak"], r["oran_kaynak"]}
    kodlar |= {r["kaynak"] for r in m.oku_enag()}
    for k in sorted(kodlar - {""}):
        assert f"| {k} |" in txt, f"{k} kodu SOURCES.md'de tanimli degil"


def test_yayimlanan_yillik_oranlar(m):
    assert str(m.TUIK_YOY) == "31.51"
    assert str(m.ENAG_YOY) == "49.03"


# ---------------------------------------------------------------------- katman A
def test_a_hicbir_ay_toleransi_asmiyor(res):
    assert res["A"]["fail"] == 0
    assert res["A"]["ay_sayisi"] == 64


def test_a_en_buyuk_artik(res):
    assert res["A"]["en_buyuk_artik"] == "0.004978"
    assert res["A"]["ortalama_artik"] == "0.002485"


def test_a_tolerans_sabit_degil(res):
    """QA bulgusu: duz +-0,005 pp yanlisti. Yaricap aya gore degismeli."""
    lo = res["A"]["tolerans_yaricap_min"]
    hi = res["A"]["tolerans_yaricap_max"]
    assert lo != hi, "tolerans yaricapi sabit cikti, formul yanlis uygulanmis"
    assert lo == "0.005288" and hi == "0.007126"
    assert float(lo) > 0.005, "dogru zarf, hatali duz 0,005'ten genis olmali"


def test_a_her_satir_kendi_araliginda(res):
    for s in res["A"]["satirlar"]:
        assert float(s["tolerans_alt"]) <= float(s["yayimlanan"]) <= float(s["tolerans_ust"])


# ---------------------------------------------------------------------- katman B
def test_b_tuik(res):
    b = res["Bt"]
    assert b["bilesik"] == "31.491938"
    assert b["fark_pp"] == "-0.018062"
    assert b["zarf_alt"] == "31.409838" and b["zarf_ust"] == "31.574080"
    assert b["zarf_kullanim_yuzde"] == "22.0"
    assert b["uyumlu"]


def test_b_enag(res):
    b = res["Be"]
    assert b["bilesik"] == "49.046410"
    assert b["fark_pp"] == "0.016410"
    assert b["zarf_alt"] == "48.954924" and b["zarf_ust"] == "49.137943"
    assert b["zarf_kullanim_yuzde"] == "17.9"
    assert b["uyumlu"]


def test_b_ana_bulgu_iki_taraf_da_geciyor(res):
    """Raporun omurgasi. Bu kirilirsa baslik yanlis olur."""
    assert res["Bt"]["uyumlu"] and res["Be"]["uyumlu"]


def test_b_ayni_test_ayni_tolerans(m):
    """Simetri: iki kuruma farkli standart uygulanmadigini kanitla."""
    import inspect
    src = inspect.getsource(m.katman_b)
    assert "TUIK" not in src and "ENAG" not in src, \
        "katman_b kuruma ozel dal iceriyor, test simetrik degil"


# ---------------------------------------------------------------------- katman C
def test_c_sentetik_endeks_ve_band(res):
    c = res["C"]
    assert c["sentetik_endeks"] == "4288.77"
    assert c["sentetik_band"] == ["4287.10", "4290.45"]
    assert c["son_resmi_ay"] == "2025-12"
    assert c["zincirlenen_ay"] == 8, "2026'nin 8 ayi sentetik olarak zincirleniyor"


def test_c_carpan_ve_alim_gucu(res):
    c = res["C"]
    assert c["carpan"] == "8.9872"
    assert c["carpan_band"] == ["8.9837", "8.9907"]
    assert c["kumulatif_artis_yuzde"] == "798.72"
    assert c["yuz_tl_bugun"] == "898.72"
    assert c["bir_tl_kurus"] == "11.13"


def test_c_adim_ve_gozlem_ayrimi(res):
    """QA bulgusu: 71 adim sayisi, 72 gozlem sayisi. Karistirilmamali."""
    c = res["C"]
    assert c["zincir_adimi_ay"] == 71
    assert c["gozlem_etiketi_ay"] == 72
    assert c["gozlem_etiketi_ay"] - c["zincir_adimi_ay"] == 1


# ---------------------------------------------------------------------- katman D
def test_d_karne(res):
    assert res["D"]["tuik"] == "8/8"
    assert res["D"]["enag"] == "2/8"


def test_d_enag_gectigi_ikisi_ozdeslik_testi(res):
    gecti = [o["olcut"] for o in res["D"]["olcutler"] if o["enag"]]
    assert len(gecti) == 2
    assert all("ozdeslik" in g for g in gecti)


# --------------------------------------------------------------- rapor butunlugu
def test_rapor_zorunlu_uyarilari_iceriyor():
    """QA'in FAIL verdigi noktalar rapordan silinemesin."""
    t = (AUDIT_DIR / "README.md").read_text(encoding="utf-8")
    for zorunlu in [
        "SENTETİKTİR",
        "özdeşlik kontrolüdür",
        "yeniden üretemedik",
        "hakedis.org",
        "71 zincir adımı",
        "Ön-kayıt bu turda kısmi",
        "doğruluk sıralaması **değildir**",
    ]:
        assert zorunlu in t, f"rapordan zorunlu uyari silinmis: {zorunlu}"


def test_rapor_kalici_yokluk_iddiasi_icermiyor():
    t = (AUDIT_DIR / "README.md").read_text(encoding="utf-8")
    assert "ENAG'ın verisi kontrol edilemez" not in t.replace("**demiyoruz**", "@") \
        or "demiyoruz" in t


def test_rapor_ve_protokolde_uzun_tire_yok():
    for p in (AUDIT_DIR / "README.md", AUDIT_DIR / "PROTOCOL.md", AUDIT_PY):
        t = p.read_text(encoding="utf-8")
        assert "\u2014" not in t and "\u2013" not in t, f"{p.name} uzun tire iceriyor"


def test_protokol_sonuclardan_once_commit_edilmis():
    """On-kaydin sahiciligi git gecmisinden dogrulanir, iddiadan degil."""
    def ilk_commit(path):
        out = subprocess.run(
            ["git", "log", "--reverse", "--format=%ct", "--", path],
            cwd=ROOT, capture_output=True, text=True,
        )
        satirlar = [x for x in out.stdout.split() if x.strip()]
        return int(satirlar[0]) if satirlar else None

    p = ilk_commit("audits/001-tufe-aritmetigi/PROTOCOL.md")
    r = ilk_commit("audits/001-tufe-aritmetigi/data/tuik_tufe.csv")
    if p is None or r is None:
        pytest.skip("git gecmisi yok (shallow clone)")
    assert p <= r, "PROTOCOL.md sonuclardan sonra commit edilmis, on-kayit gecersiz"


# ----------------------------------------------------------------- ucdan uca
def test_check_bayragi_sifir_donuyor():
    r = subprocess.run([sys.executable, str(AUDIT_PY), "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tamami veriyle uyusuyor" in r.stdout


def test_veri_bozulunca_check_kiriliyor(tmp_path):
    """Mutasyon testi: cengel gercekten caliyor mu."""
    import shutil
    hedef = tmp_path / "001-tufe-aritmetigi"
    shutil.copytree(AUDIT_DIR, hedef)
    csv_p = hedef / "data" / "tuik_tufe.csv"
    csv_p.write_text(csv_p.read_text(encoding="utf-8")
                     .replace("2026-08,1.84", "2026-08,1.94"), encoding="utf-8")
    r = subprocess.run([sys.executable, str(hedef / "audit.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 1, "veri bozuldu ama --check yesil kaldi, cengel calismiyor"
    assert "SAPMA" in r.stdout
