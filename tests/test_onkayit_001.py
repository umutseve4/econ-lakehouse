"""Denetim 001'in on-kayit sirasini git gecmisinden dogrular.

Bu dosyanin varlik sebebi: "protokolu sonuclardan once sabitledim" cumlesi
bir iddiadir. Iddiayi kanit yapan sey git gecmisidir, dosyanin icindeki
cumle degil. Burasi o gecmisi okur.

Neden ayri bir dosya: tests/test_audit_001.py icindeki eski sira kontrolu
iki noktada zayifti.

  1. Yalnizca HEAD gecmisine bakiyordu. Squash merge, ayri commit'lerde
     duran on-kayit kanitini tek commit'e duzlestirir. O durumda protokol
     ile sonuclarin "ilk commit"i ayni commit cikar, `p <= r` kiyaslamasi
     kendisiyle yapilir ve test bos yere yesil kalir. Denetim 002 tam
     olarak boyle kirildi.
  2. Gecmis bulunamazsa `pytest.skip` ediyordu. Kanitin yoklugu, kanitin
     kendisi gibi raporlaniyordu.

Burada ayni iddia uc noktadan baglanir:

  1. PROTOCOL.md, sonuc dosyalarina dokunmayan kendi commit'inde durur.
  2. O commit, sonuc dosyalarinin ilk commit'inin topolojik atasidir.
     Zaman damgasi degil ata iliskisi kullanilir, cunku zaman damgasi
     yeniden yazilabilir ve saat kaymasindan etkilenir.
  3. Kontrolun kendisi calisir durumdadir: yapay depolarda kurulan squash
     ve ters sirali gecmisler FAIL verir.

Not: Denetim 001'in on-kaydi PROTOCOL.md bolum 6'da acikca **kismi** ilan
edilmistir (protokol, ham veri toplandiktan sonra ama nihai rapor
yazilmadan once sabitlenmistir). Bu dosya o kismi iddiayi dogrular, daha
guclusunu degil. Asagidaki testlerden biri o caydiriciligin raporda
yazili kalmasini da garanti eder.
"""
from __future__ import annotations

import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

PROTOKOL = "audits/001-tufe-aritmetigi/PROTOCOL.md"
SONRAKILER = [
    "audits/001-tufe-aritmetigi/audit.py",
    "audits/001-tufe-aritmetigi/data/tuik_tufe.csv",
    "audits/001-tufe-aritmetigi/data/enag_etufe.csv",
    "audits/001-tufe-aritmetigi/data/SOURCES.md",
]


# ------------------------------------------------------------------ git yardimcilari
def _git(*args: str, depo: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(depo or ROOT),
        capture_output=True,
        text=True,
    )


def _git_deposu_mu(depo: pathlib.Path | None = None) -> bool:
    return _git("rev-parse", "--git-dir", depo=depo).returncode == 0


def _ilk_commit(yol: str, depo: pathlib.Path | None = None) -> str | None:
    """Yolu ekleyen EN ESKI commit. Tum ref'ler taranir.

    `--all` kritik. Varsayilan `git log` yalnizca HEAD'den ulasilabilen
    commit'leri gezer; squash edilmis bir dalin ozgun commit'leri orada
    gorunmez ama depoda durur.
    """
    out = _git("log", "--all", "--reverse", "--format=%H", "--", yol, depo=depo)
    satirlar = [s for s in out.stdout.split() if s.strip()]
    return satirlar[0] if satirlar else None


def _committeki_dosyalar(sha: str, depo: pathlib.Path | None = None) -> set[str]:
    out = _git("show", "--pretty=format:", "--name-only", sha, depo=depo)
    return {s.strip() for s in out.stdout.splitlines() if s.strip()}


def _ata_mi(once: str, sonra: str, depo: pathlib.Path | None = None) -> bool:
    return _git("merge-base", "--is-ancestor", once, sonra, depo=depo).returncode == 0


def _ihlaller(
    depo: pathlib.Path | None = None,
    protokol: str = PROTOKOL,
    sonrakiler: list[str] | None = None,
) -> list[str]:
    """On-kayit kuralinin ihlallerini dondurur. Bos liste = kural saglandi."""
    sonrakiler = SONRAKILER if sonrakiler is None else sonrakiler
    hatalar: list[str] = []

    p = _ilk_commit(protokol, depo)
    if p is None:
        return ["%s git gecmisinde hic gorunmuyor, on-kayit kanitlanamaz" % protokol]

    fazlalik = sorted(_committeki_dosyalar(p, depo) - {protokol})
    if fazlalik:
        hatalar.append(
            "protokol commit'i %s yalniz basina degil, su dosyalari da iceriyor: %s"
            % (p[:8], fazlalik)
        )

    for yol in sonrakiler:
        s = _ilk_commit(yol, depo)
        if s is None:
            hatalar.append("%s git gecmisinde hic gorunmuyor" % yol)
            continue
        if s == p:
            hatalar.append(
                "%s protokolle AYNI commit'te (%s). Gecmis squash edilmis olabilir; "
                "bu haliyle sira kanitlanamaz." % (yol, p[:8])
            )
            continue
        if not _ata_mi(p, s, depo):
            hatalar.append(
                "protokol commit'i %s, %s commit'inin (%s) atasi degil, sira ters"
                % (p[:8], yol, s[:8])
            )
    return hatalar


# --------------------------------------------------------------------- gercek depo
def _gercek_depo_yoksa_atla() -> None:
    if not _git_deposu_mu():
        pytest.skip("burasi bir git deposu degil (sdist ya da arsiv kopyasi)")


def test_gercek_depo_gecmisi_okunabiliyor():
    """Once gecmisin GERCEKTEN okunabildigini kanitla.

    Shallow clone'da (fetch-depth: 1) bu test kirilir. Amac budur: sessiz
    bir skip yerine gurultulu bir kirmizi. Kapinin dayandigi varsayim
    bozulduysa bunu ogrenmemiz gerekir.
    """
    _gercek_depo_yoksa_atla()
    assert _ilk_commit(PROTOKOL) is not None, (
        "PROTOCOL.md'nin ilk commit'i bulunamadi. Tam gecmis gerekiyor: "
        "actions/checkout adiminda fetch-depth: 0 olmali."
    )


def test_protokol_kendi_basina_commit_edilmis():
    """Protokol commit'i sonuc dosyalarina dokunmamis olmali.

    Protokol ile veriyi ayni commit'e koymak, on-kaydin tamamini anlamsiz
    kilar: hangisinin once yazildigi artik gecmisten okunamaz.
    """
    _gercek_depo_yoksa_atla()
    p = _ilk_commit(PROTOKOL)
    assert p is not None
    assert _committeki_dosyalar(p) == {PROTOKOL}, (
        "protokol commit'i %s tek basina degil: %s"
        % (p[:8], sorted(_committeki_dosyalar(p)))
    )


def test_protokol_sonuclarin_atasi():
    _gercek_depo_yoksa_atla()
    hatalar = _ihlaller()
    assert not hatalar, "on-kayit sirasi bozuk:\n  - " + "\n  - ".join(hatalar)


def test_protokol_kismi_on_kayit_caydiriciligini_koruyor():
    """Zayif iddia sessizce guclendirilemesin.

    Denetim 001'in on-kaydi kismidir ve PROTOCOL.md bunu yaziyor. Bu
    cumle silinirse repo, git gecmisinin destekledigi seyden fazlasini
    iddia etmis olur.
    """
    t = (ROOT / PROTOKOL).read_text(encoding="utf-8")
    assert "kismidir" in t or "k\u0131smidir" in t, (
        "PROTOCOL.md bolum 6'daki 'on-kayit kismidir' caydiriciligi silinmis"
    )


# ------------------------------------------------------------- kontrolun kendisi
def _yapay_depo(kok: pathlib.Path, senaryo: str) -> pathlib.Path:
    """Bilinen bir gecmis kurar ve yolunu dondurur.

    senaryo:
      dogru   protokol once, kendi commit'inde, sonuclar sonra
      squash  hepsi tek commit'te (squash merge'un yaptigi sey)
      ters    sonuclar once, protokol sonra
    """
    depo = kok / senaryo
    (depo / "audits" / "001-tufe-aritmetigi" / "data").mkdir(parents=True)
    _git("init", "-q", "-b", "ana", depo=depo)
    _git("config", "user.email", "test@ornek.gecersiz", depo=depo)
    _git("config", "user.name", "Test", depo=depo)
    _git("config", "commit.gpgsign", "false", depo=depo)

    protokol_dosya = depo / PROTOKOL
    sonuc_dosya = depo / SONRAKILER[0]

    def yaz_protokol() -> None:
        protokol_dosya.write_text("protokol\n", encoding="utf-8")

    def yaz_sonuc() -> None:
        sonuc_dosya.write_text("sonuc\n", encoding="utf-8")

    def commitle(mesaj: str) -> None:
        _git("add", "-A", depo=depo)
        _git("commit", "-q", "--no-gpg-sign", "-m", mesaj, depo=depo)

    if senaryo == "dogru":
        yaz_protokol()
        commitle("protokol")
        yaz_sonuc()
        commitle("sonuclar")
    elif senaryo == "squash":
        yaz_protokol()
        yaz_sonuc()
        commitle("protokol ve sonuclar tek commit'te")
    elif senaryo == "ters":
        yaz_sonuc()
        commitle("sonuclar")
        yaz_protokol()
        commitle("protokol")
    else:
        raise ValueError(senaryo)
    return depo


def test_negatif_kontrol_dogru_gecmis_geciyor(tmp_path):
    depo = _yapay_depo(tmp_path, "dogru")
    assert _ihlaller(depo=depo, sonrakiler=[SONRAKILER[0]]) == []


def test_negatif_kontrol_squash_yakalaniyor(tmp_path):
    """Denetim 002'yi kiran senaryonun ta kendisi."""
    depo = _yapay_depo(tmp_path, "squash")
    hatalar = _ihlaller(depo=depo, sonrakiler=[SONRAKILER[0]])
    assert hatalar, "squash edilmis gecmis yakalanmadi, kontrol sahte yesil veriyor"
    assert any("AYNI commit" in h for h in hatalar)


def test_negatif_kontrol_ters_sira_yakalaniyor(tmp_path):
    depo = _yapay_depo(tmp_path, "ters")
    hatalar = _ihlaller(depo=depo, sonrakiler=[SONRAKILER[0]])
    assert hatalar, "ters sirali gecmis yakalanmadi, kontrol sahte yesil veriyor"
    assert any("atasi degil" in h for h in hatalar)
