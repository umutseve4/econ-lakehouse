# Kaynak haritasi

Her veri hucresi bir kaynak koduna baglidir. CSV dosyalarindaki
`kaynak` / `endeks_kaynak` / `oran_kaynak` sutunlari bu tabloya isaret eder.

| kod | ne icin | URL |
|---|---|---|
| T1 | TUIK TUFE aylik ve yillik degisim oranlari | https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Istatistikler/Enflasyon+Verileri/Tuketici+Fiyatlari |
| T2 | TUIK TUFE 2003=100 endeks duzeyi arsivi | https://www.hakedis.org/endeksler/tuketici-fiyat-genel-endeksi-ve-degisim-oranlari-2003 |
| T3 | TUIK resmi bulten, TUFE Agustos 2026, sayi 58290, 03.09.2026 10:00 | https://veriportali.tuik.gov.tr/tr/press/58290 |
| T4 | TUIK resmi duyuru, 2025=100 baz yili degisimi, 30.10.2025 | https://www.tuik.gov.tr/media/announcements/TUFE_Duyuru30102025.pdf |
| T5 | TUIK resmi bulten, TUFE Ocak 2026 (yeni seri 2025=100) | https://veriportali.tuik.gov.tr/Bulten/Index?p=Tuketici-Fiyat-Endeksi-Ocak-2026-58293 |
| T6 | TCMB analizi, 2026 TUFE guncellemeleri ve etkileri | https://www.tcmb.gov.tr/wps/wcm/connect/blog/tr/main+menu/analizler/2026+yili+tuketici+fiyat+endeksindeki+guncellemeler+ve+etkileri |
| T7 | SBB, Agustos 2026 fiyat gelismeleri (bagimsiz teyit) | https://www.sbb.gov.tr/2026-yili-agustos-ayi-tuketici-ve-uretici-fiyat-gelismeleri-aciklandi/ |
| E1 | ENAG 2026 Ocak-Agustos aylik ve yillik oranlari | https://www.marasanahaber.com.tr/enag-agustos-2026-enflasyonunu-acikladi-yillik-artis-yuzde-49-03/56313/ |
| E2 | ENAG 2025 Agustos-2026 Temmuz aylik oranlari | https://sinantankutgulhan.com/turkiyede-enflasyon-enag-tuik-ve-ito-karsilastirmasi/ |
| E3 | ENAG Agustos 2026, aylik 2,24 / yillik 49,03 (bagimsiz teyit) | https://ankahaber.net/haber/enag-enflasyon-agustos-ayinda-aylik-yuzde-2-24-aylik-yuzde-49-03-oldu-e1c5b9e8 |
| E4 | ENAG Temmuz 2026, aylik 3,07 / yillik 50,49 (bagimsiz teyit) | https://www.borsaningundemi.com/haber/enagin-tufe-verileri-aciklandi-iste-temmuz-enflasyonu-1903815 |
| E5 | ENAG donemsel bulten ornegi (tam seri degil) | https://enagrup.org/bulten/mrt23en.pdf?v1 |

## Bilinen kaynak zaafi

TUIK rakamlari birincil kaynaktan (resmi bulten ve TCMB tablosu) alinmistir.

ENAG rakamlari **ikincil kaynaklardan** derlenmistir. ENAG'in kendi sitesinde
Eylul 2020'den bugune kesintisiz, makine-okunur bir seri bulunamamistir.
Bu, iki kurumun verisinin ayni kanit gucunde olmadigi anlamina gelir ve
raporun her yerinde acikca belirtilmistir.

Erisim denemesi: 2026-09-10 18:11 UTC, `enagrup.org`, `enagrup.org/endeks/`
ve `enagrup.org/e-tufe/` adreslerinin ucu de Cloudflare 525 "SSL handshake
failed" dondurdu. Cloudflare Ray ID: a390658a1def72aa, a390658dbc59674a,
a3906595eaf4f981 (uc ayri edge: Newark, Atlanta, Newark).

Bu tek bir zaman noktasindaki gozlemdir ve kalici erisilemezlik kanitlamaz.
