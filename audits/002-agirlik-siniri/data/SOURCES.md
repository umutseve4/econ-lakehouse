# Denetim 002. Kaynaklar

Her veri hucresinin bir kaynak kodu vardir. Ikincil kaynaklar acikca ikincil
isaretlenmistir. Bu denetimin sonucu ikincil bir kaynaga dayanmaktadir ve bu
gizlenmemistir; raporun "kendi zaaflari" bolumunde ilk madde budur.

## Kod P1. BIRINCIL

TUIK, "Tuketici Fiyat Endeksi, Agustos 2026", Sayi 58290, yayimlanma tarihi
03 Eylul 2026 saat 10:00.

https://veriportali.tuik.gov.tr/tr/press/58290/metadata

Bu kaynaktan dogrudan alinan hucreler:

| hucre | deger |
|---|---:|
| Genel TUFE yillik degisim, 2026-08 | 31.51 |
| Genel TUFE aylik degisim, 2026-08 | 1.84 |
| Gida ve alkolsuz icecekler, yillik oran | 33.79 |
| Konut, su, elektrik, gaz ve diger yakitlar, yillik oran | 39.77 |
| Ulastirma, yillik oran | 35.08 |
| Gida ve alkolsuz icecekler, yillik katki | 8.12 |
| Konut, su, elektrik, gaz ve diger yakitlar, yillik katki | 5.01 |
| Ulastirma, yillik katki | 5.94 |

Bulten metni kalan gruplar icin Ek Tablo-1 ve Ek Tablo-3'e yonlendirmektedir.
Bu iki ek tablo dosyasina bu calisma sirasinda kullanilan arac zinciriyle
dogrudan erisilemedi. Bu bir sinirdir ve S1'e basvurma nedenidir.

## Kod S1. IKINCIL

BMD, "Tuketici Fiyat Endeksi, Agustos 2026". "Agustos 2026 TUFE" tablosunda
13 ana harcama grubunun agirlik, aylik degisim, aylik katki, yillik degisim ve
yillik katki degerlerini TUIK kaynakli olarak tam halde yeniden yayimlamaktadir.

https://www.bmd.com.tr/application/files/9517/8885/2758/Tuketici_Fiyat_Endeksi_-_Agustos_2026.pdf

13 grubun agirlik, yillik oran ve yillik katki degerlerinin tamami bu
kaynaktan alinmistir. Yukaridaki P1 hucreleri S1 ile karsilastirilmis ve
birebir ayni cikmistir; bu, S1'in en az bu sekiz hucrede TUIK ile uyumlu
oldugunu gosterir, tablonun tamaminin dogrulugunu kanitlamaz.

S1'de gecen kisaltilmis grup etiketleri ("Ev Esyasi", "Eglence ve Kultur",
"Egitim", "Lokanta ve Konak.", "Cesitli Mal ve Hiz.") CSV'de TUIK'in
COICOP 2018 tam grup adlariyla yazilmistir. Hicbir sayisal deger
degistirilmemistir.

## Kod S2. IKINCIL, tam bulten kopyasi

ISTIB uzerinde barindirilan TUIK Agustos 2026 bulten PDF'i.

https://www.istib.org.tr/Assets/raporpdf/aaa413f8-04f3-46f6-95a7-552462152efb.pdf

Bu kopyanin icindeki ek tablolara bu ortamda erisilemedi. Kayit icin
listelenmistir, hicbir hucre bu kaynaktan alinmamistir.

## ENAG

Agustos 2026 yillik oran: 49.03. Bu deger Denetim 001'de kullanilan ve orada
kaynaklanan degerle aynidir; bkz. `audits/001-tufe-aritmetigi/data/SOURCES.md`.
Denetim 002'de bu sayi yalnizca baglam icin anilir. Katman A kirildigi ve
durdurma kurali 1 islediginden, bu denetimde ENAG orani uzerine **hicbir
hesap kurulmamistir**.

`enagrup.org` bu calisma sirasinda kullanilan arac zincirine HTTP 403
dondurmustur. ENAG ile ilgili her sey bu nedenle ikincil kaynaklidir.

## Ondalik basamak ve yuvarlama

Agirliklar, oranlar ve katkilarin tamami iki ondalikla yayimlanmistir.
Bu nedenle yuvarlama yari genisligi her hucre icin h = 0.005 alinmistir.
Protokoldeki zarf formulu bu degeri kullanir.

Kaynak tablonun toplam satiri 100.00'dur. 13 grup agirliginin iki ondalikli
hallerinin aritmetik toplami 99.97'dir. Aradaki 0.03'luk fark yuvarlamadan
gelmektedir ve 13 x 0.005 = 0.065 payinin icindedir. Degerler yeniden
olceklendirilmemis, yayimlandigi gibi birakilmistir.
