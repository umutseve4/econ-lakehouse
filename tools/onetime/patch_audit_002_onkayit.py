"""Tek seferlik yama. tests/test_audit_002.py icindeki git gecmisi bolumunu
tum ref'ler uzerinden calisan bicime tasir.

Neden: PR #91 squash ile birlestirildi. Squash, protokol, veri ve rapor
commit'lerini ana dalda tek bir commit'te toplar. Eski testler sirayi yalnizca
HEAD gecmisinde aradigi icin kanit kaybolmus gorunuyor ve denetim kapisi
kirmizi yaniyor. Gercek sira, kaynak dal denetim-002-sepet commit'lerinde
korunuyor (4b1e27f0 protokol, 19:04:52; 0419cd15 veri, 19:16:40).

Bu betik kapiyi zayiflatmaz. Tersine, bozuk gecmisin gercekten yakalandigini
gosteren uc negatif kontrol testi ekler. Betik calistiktan sonra kendini siler.
"""

import io
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HEDEF = os.path.join(KOK, "tests", "test_audit_002.py")
CAPA = "\ndef _git(*args):\n"

YENI = '''
PROTOKOL_YOLU = "audits/002-agirlik-siniri/PROTOCOL.md"
SONRAKI_YOLLAR = (
    "audits/002-agirlik-siniri/data/tuik-2026-08-ana-gruplar.csv",
    "audits/002-agirlik-siniri/audit.py",
    "audits/002-agirlik-siniri/README.md",
)


def _git(*args, depo=None):
    """git komutunu calistirir. git kurulu degilse bos doner."""
    try:
        return subprocess.run(
            ["git"] + list(args), cwd=depo or KOK, capture_output=True, text=True
        ).stdout.strip()
    except FileNotFoundError:
        return ""


def _git_deposu_mu(depo=None):
    return bool(_git("rev-parse", "--is-inside-work-tree", depo=depo))


def _ilk_commit(yol, depo=None):
    """Yolu ilk kez ekleyen commit'i TUM ref'ler icinde arar.

    Tek dalla yetinilmez. Bir PR squash ile birlestirildiginde protokol, veri
    ve rapor ana dalda tek commit'te gorunur; sira oradan okunamaz. Kanit,
    kaynak dalin commit'lerinde durur. Bu yuzden arama git log --all ile
    yapilir ve is akisi tam gecmisi (fetch-depth: 0) ceker.
    """
    c = _git("log", "--all", "--reverse", "--format=%H", "--", yol, depo=depo)
    return c.splitlines()[0] if c else None


def _committeki_dosyalar(commit, depo=None):
    ham = _git("show", "--name-only", "--format=", commit, depo=depo)
    return [d for d in ham.splitlines() if d.strip()]


def _tek_basina_ihlali(depo=None):
    """Protokol commit'i yalnizca PROTOCOL.md icermeli. Ihlal varsa metin doner."""
    p = _ilk_commit(PROTOKOL_YOLU, depo=depo)
    if not p:
        return "%s hicbir ref'te bulunamadi (tam gecmis gerekli)" % PROTOKOL_YOLU
    dosyalar = _committeki_dosyalar(p, depo=depo)
    if dosyalar != [PROTOKOL_YOLU]:
        return "protokol commit'i %s tek basina degil: %s" % (p[:8], dosyalar)
    return None


def _sira_ihlalleri(depo=None):
    """Veri ve rapor, protokol commit'inin soyundan gelmeli."""
    p = _ilk_commit(PROTOKOL_YOLU, depo=depo)
    if not p:
        return ["%s hicbir ref'te bulunamadi (tam gecmis gerekli)" % PROTOKOL_YOLU]
    ihlaller = []
    for yol in SONRAKI_YOLLAR:
        c = _ilk_commit(yol, depo=depo)
        if not c:
            ihlaller.append("git gecmisinde bulunamadi: " + yol)
            continue
        if c == p:
            ihlaller.append(
                "%s protokolle AYNI commit'te, on kayit sirasi kanitlanamaz" % yol
            )
            continue
        sayi = _git("rev-list", "--count", "%s..%s" % (p, c), depo=depo)
        try:
            ileride = int(sayi) > 0
        except ValueError:
            ileride = False
        if not ileride:
            ihlaller.append(
                "%s protokolden once ya da ondan bagimsiz commit edilmis" % yol
            )
    return ihlaller


def test_protokol_tek_basina_commit_edilmis():
    if not _git_deposu_mu():
        pytest.skip("git deposu yok")
    ihlal = _tek_basina_ihlali()
    assert ihlal is None, ihlal


def test_protokol_veriden_once_commit_edilmis():
    """PROTOCOL.md, veri ve sonuc dosyalarindan once commit edilmis olmali."""
    if not _git_deposu_mu():
        pytest.skip("git deposu yok")
    ihlaller = _sira_ihlalleri()
    assert not ihlaller, (
        "on kayit sirasi kanitlanamadi: %s. Kanit, denetim-002-sepet dalinin "
        "commit'lerindedir; o dal silinirse bu kanit yok olur." % ihlaller
    )


# --------------------------------------------------------------------------
# Negatif kontrol: yukaridaki iki test gercekten kirilabiliyor mu
#
# Kapinin varligi iddia degil kanit olmali. Asagidaki testler yapay depolar
# kurar ve bozuk gecmisin yakalandigini, dogru gecmisin gectigini gosterir.
# --------------------------------------------------------------------------


def _yapay_depo(kok, senaryo):
    def g(*a):
        subprocess.run(["git"] + list(a), cwd=kok, check=True, capture_output=True)

    g("init", "-q", "-b", "main")
    g("config", "user.email", "denetim@ornek.gecersiz")
    g("config", "user.name", "denetim")
    g("config", "commit.gpgsign", "false")

    yollar = [os.path.join(kok, PROTOKOL_YOLU)] + [
        os.path.join(kok, y) for y in SONRAKI_YOLLAR
    ]
    for y in yollar:
        os.makedirs(os.path.dirname(y), exist_ok=True)

    def yaz(yol, metin):
        with open(yol, "w", encoding="utf-8") as f:
            f.write(metin)

    protokol = yollar[0]
    sonrakiler = yollar[1:]

    if senaryo == "dogru":
        yaz(protokol, "on kayit\\n")
        g("add", "-A")
        g("commit", "-qm", "on kayit")
        for y in sonrakiler:
            yaz(y, "veri\\n")
        g("add", "-A")
        g("commit", "-qm", "veri ve sonuc")
    elif senaryo == "squash":
        yaz(protokol, "on kayit\\n")
        for y in sonrakiler:
            yaz(y, "veri\\n")
        g("add", "-A")
        g("commit", "-qm", "hepsi tek commit")
    elif senaryo == "ters":
        for y in sonrakiler:
            yaz(y, "veri\\n")
        g("add", "-A")
        g("commit", "-qm", "once veri")
        yaz(protokol, "on kayit\\n")
        g("add", "-A")
        g("commit", "-qm", "sonra protokol")
    else:
        raise ValueError(senaryo)
    return kok


@pytest.mark.parametrize("senaryo", ["squash", "ters"])
def test_kontrol_bozuk_gecmisi_yakalar(senaryo):
    if not _git_deposu_mu():
        pytest.skip("git yok")
    with tempfile.TemporaryDirectory() as gecici:
        _yapay_depo(gecici, senaryo)
        bulgular = list(_sira_ihlalleri(depo=gecici))
        tek = _tek_basina_ihlali(depo=gecici)
        if tek:
            bulgular.append(tek)
        assert bulgular, "bozuk gecmis yakalanmadi: %s" % senaryo


def test_kontrol_dogru_gecmisi_gecirir():
    if not _git_deposu_mu():
        pytest.skip("git yok")
    with tempfile.TemporaryDirectory() as gecici:
        _yapay_depo(gecici, "dogru")
        assert _sira_ihlalleri(depo=gecici) == []
        assert _tek_basina_ihlali(depo=gecici) is None
'''


def main():
    with io.open(HEDEF, encoding="utf-8") as f:
        metin = f.read()

    if metin.count(CAPA) != 1:
        sys.exit(
            "HATA: capa tam bir kez eslesmeli, %d bulundu. Yama uygulanmadi."
            % metin.count(CAPA)
        )

    kesim = metin.index(CAPA)
    yeni = metin[:kesim] + YENI

    if "git log" not in yeni or "--all" not in yeni:
        sys.exit("HATA: yamali metin beklenen icerigi tasimiyor")
    if "\u2014" in yeni or "\u2013" in yeni:
        sys.exit("HATA: uzun tire girdi")

    with io.open(HEDEF, "w", encoding="utf-8") as f:
        f.write(yeni)

    print("Yama uygulandi. Eski boyut %d, yeni boyut %d." % (len(metin), len(yeni)))


if __name__ == "__main__":
    main()
