# Denetim 001. İki taraf da doğru topluyor. Fark aritmetikte değil, sepette.

**Soru:** TÜİK Ağustos 2026 için yıllık enflasyonu %31,51, ENAG %49,03 açıkladı.
Bu farkın kaynağı taraflardan birinin **aritmetik hatası** mı?

**Cevap: Hayır.** Test edilebilen aritmetiği her iki kurum da geçiyor.

| | iç aritmetik testi | yeniden üretilebilirlik |
|---|---|---|
| **TÜİK** | GEÇTİ (64/64 ay temiz) | 8/8 |
| **ENAG** | GEÇTİ (zarfın %17,9'u) | 2/8 |

Bu iki satır, Türkiye'deki enflasyon tartışmasının en çok kullanılan iki
cümlesini aynı anda çürütüyor:

- "TÜİK'in sayıları kendi içinde bile tutmuyor." Tutuyor. 64 ayın 64'ü,
  yayımlanan endeks düzeyinden türetilen oranla kendi yuvarlama aralığında.
- "ENAG rakamı uyduruyor." Bu iddia, bu testle desteklenmiyor. ENAG'ın 12 aylık
  oranı bileşiklendiğinde kendi yayımladığı yıllık orana yuvarlama payının
  içinde çıkıyor.

İkisi de doğru topluyorsa, %17,5 puanlık fark toplama hatasından gelmiyor.
Sepetten, ağırlıktan ve fiyat derleme yönteminden geliyor.

Gerçek asimetri şurada: TÜİK'in sonucunu üçüncü bir kişi baştan sona yeniden
üretebiliyor, ENAG'ınkini üretemiyor. Bu bir **doğruluk** yargısı değil, bir
**denetlenebilirlik** yargısı.

---

## Bunu kendin çalıştır

```bash
git clone https://github.com/umutseve4/econ-lakehouse
cd econ-lakehouse
python audits/001-tufe-aritmetigi/audit.py --check
```

Bağımlılık yok, sadece standart kütüphane. Aşağıdaki her sayı bu betik
tarafından ham CSV'den yeniden hesaplanır. Bir sayı tutmazsa çıkış kodu 1 olur
ve CI kırmızıya döner. Rapor kendini doğrulayan bir artefakttır.

Protokol sonuçlardan **önce** commit edilmiştir: [PROTOCOL.md](PROTOCOL.md).
Sırayı `git log --reverse --format='%h %ad %s' --date=iso -- audits/001-tufe-aritmetigi/`
ile kendin doğrulayabilirsin.

---

## Katman A. TÜİK endeks düzeyi ile aylık oran birbirini tutuyor mu

TÜİK iki şeyi ayrı ayrı yayımlıyor: 2003=100 endeks düzeyi ve aylık yüzde
değişim. İkisi aynı hesaptan çıkar, dolayısıyla birbirini tutmak zorundadır.

**Pencere:** Eylül 2020 - Aralık 2025, 64 ay.

| ölçüm | değer |
|---|---|
| incelenen ay | 64 |
| toleransı aşan ay | **0** |
| en büyük mutlak artık | 0,004978 pp (2021-05) |
| ortalama mutlak artık | 0,002485 pp |
| tolerans yarıçapı | 0,005288 - 0,007126 pp, **aya göre değişir** |

### Tolerans neden sabit değil

İlk denememde düz `±0,005 pp` kullandım. **Bu yanlıştı.** O değer yalnızca
yayımlanan oranın kendi yuvarlamasını karşılar; endeks düzeylerinin de
yuvarlı olduğunu yok sayar. Gerçek endeksler `A ∈ [a-h, a+h]` ve
`B ∈ [b-h, b+h]` aralığında, `h = 0,005`. Oranın izin verilen sınırları:

```
alt = ((a - h) / (b + h) - 1) * 100 - h
üst = ((a + h) / (b - h) - 1) * 100 + h
```

Yarıçap endeks büyüdükçe daralır: 2020'de 472 olan endekste 0,0071 pp,
2025'te 3513 olan endekste 0,0053 pp. Doğru zarf, kullandığımdan **geniş**
olduğu için karar değişmiyor. Ama düzeltmeden bırakmak sonucu şansa bırakmak
olurdu. Tam 64 satırlık artık tablosu: [results.json](results.json), `katman_A.satirlar`.

---

## Katman B. 12 aylık bileşik, yayımlanan yıllık oranla tutuyor mu

Aynı test, aynı formül, aynı tolerans, **iki kuruma da**. Tek kuruma uygulanan
test denetim değildir.

**Pencere:** Eylül 2025 - Ağustos 2026. Bu pencere TÜİK'in Ocak 2026'daki baz
yılı değişimini (2003=100 -> 2025=100, kaynak T4) tam ortasından keser.

| kurum | 12 ay bileşiği | yayımlanan yıllık | fark | yuvarlama zarfı | zarfın kullanımı | sonuç |
|---|---|---|---|---|---|---|
| TÜİK | %31,491938 | %31,51 | -0,018062 pp | [31,409838 , 31,574080] | %22,0 | **UYUMLU** |
| ENAG | %49,046410 | %49,03 | +0,016410 pp | [48,954924 , 49,137943] | %17,9 | **UYUMLU** |

İki fark da yuvarlamayla tamamen açıklanıyor ve ikisi de zarfın dörtte birinden
azını kullanıyor. İşaretlerin zıt olması anlamlı değil, yuvarlama simetriktir.

### Bu testin sınırı. Bunu atlamayın.

Bu bir **özdeşlik kontrolüdür**. Yıllık oran aynı endeksten türediğinden
`∏(Iₖ/Iₖ₋₁) = I₁₂/I₀` olur ve ara terimler sadeleşir. Yani bu test şunları
yakalar: kopyalama hatası, zincirleme hatası, seri kaydırma, kaba tutarsızlık.

Şunları **yakalamaz**:

- fiyat derlemesinin doğruluğu
- sepet madde seçimi ve ağırlıklar
- kalite düzeltmesi (hedonik) uygulaması
- ana grup sayısının 12'den 13'e çıkmasının etkisi
- ağırlık kaynağının Hanehalkı Bütçe Anketi'nden Ulusal Hesaplar'a geçmesinin etkisi
- ölçülen enflasyonun gerçek yaşam maliyetiyle ilişkisi

Bu tablo "baz yılı değişimi seriyi bozmuş mu" sorusuna **cevap vermez**. O soru
için örtüşme dönemi verisi, aynı mikro fiyatlar üzerinde eski/yeni ağırlık
karşılaştırması ve resmî bağlantı katsayıları gerekir. Bunlar kamuya açık değil.
Bu testin söylediği tek şey: baz değişimi sırasında **yayımlanan oranlar
zincirlenirken bir kopukluk oluşmamış**.

---

## Katman C. Kümülatif fiyat düzeyi

> **Bu bölümdeki Ağustos 2026 endeksi SENTETİKTİR.** TÜİK böyle bir sayı
> yayımlamıyor. Ocak 2026'dan itibaren resmî seri 2025=100 tabanında
> (kaynak T4, T5). Aşağıdaki değer, son resmî 2003=100 endeksinden
> (Aralık 2025 = 3513,87) yayımlanan sekiz aylık oranla zincirlenerek
> türetilmiştir. Resmî bir TÜİK rakamı değildir.

| ölçüm | değer | belirsizlik bandı |
|---|---|---|
| Ağustos 2026 sentetik 2003=100 | 4288,77 | [4287,10 , 4290,45] |
| Eylül 2020 -> Ağustos 2026 çarpanı | 8,9872 | [8,9837 , 8,9907] |
| kümülatif artış | %798,72 | |
| Eylül 2020'deki 100 TL bugün | **898,72 TL** | |
| Eylül 2020'deki 1 TL'nin bugünkü alım gücü | **11,13 kuruş** | |

Dönem 72 aylık gözlem, aralarında **71 zincir adımı** var. "71 ay" ifadesi
yalnızca adım sayısı olarak doğrudur, gözlem sayısı 72'dir.

Band, 8 zincirlenen ayın her birinin `±0,005` yuvarlamasından gelir. Dar
olması sonucun sağlam olduğunu gösterir, sentetik olmadığını değil.

---

## Katman D. Yeniden üretilebilirlik karnesi

Sekiz ölçüt, iki kuruma da aynen.

| ölçüt | TÜİK | ENAG |
|---|---|---|
| Resmî bülten, tarih ve sayı numaralı | EVET | HAYIR |
| Endeks DÜZEYİ yayımlanıyor, sadece oran değil | EVET | HAYIR |
| Tam tarihsel seri tek kaynaktan derlenebiliyor | EVET | HAYIR |
| Makine-okunur seri (CSV / XLSX / API) | EVET | HAYIR |
| Ayrıntılı metodoloji belgesi kamuya açık | EVET | HAYIR |
| Sepet madde sayısı ve ağırlıkları yayımlanıyor | EVET | HAYIR |
| 12 aylık özdeşlik testi UYGULANABİLDİ | EVET | EVET |
| 12 aylık özdeşlik testini GEÇTİ | EVET | EVET |
| **toplam** | **8/8** | **2/8** |

### Bu karnenin ne dediği ve ne demediği

Bu bir doğruluk sıralaması **değildir**. Bir kurum tamamen şeffaf olup yanlış
ölçebilir; bir başkası kapalı olup doğru ölçebilir. Karne yalnızca şunu ölçer:
üçüncü bir kişi, kurumun yayımladığı malzemeyle sonuca ne kadar yaklaşabiliyor.

### ENAG hakkında kullandığımız ifade

"ENAG'ın verisi kontrol edilemez" **demiyoruz**. Bu, tek bir zaman noktasındaki
gözlemden kalıcı yokluk çıkarmak olurdu ve geçersizdir.

Dediğimiz şu: **2026-09-10 tarihinde, incelediğimiz kamuya açık kaynaklarla,
ENAG'ın E-TÜFE serisini uçtan uca yeniden üretemedik.**

Somut olarak: 2026-09-10 18:11 UTC'de `enagrup.org`, `enagrup.org/endeks/` ve
`enagrup.org/e-tufe/` adreslerinin üçü de Cloudflare 525 "SSL handshake failed"
döndürdü. Üç ayrı Cloudflare edge (Newark, Atlanta, Newark), Ray ID
`a390658a1def72aa`, `a390658dbc59674a`, `a3906595eaf4f981`. Bu bir anlık
gözlemdir. ENAG bu belgeleri yayımlıyor ya da yayımlayacaksa, karne değişir ve
bu rapor güncellenir.

---

## Bu raporun kendi zaafları

Bunları saklamak yerine yazıyoruz, çünkü denetimin kendisi denetlenebilir olmalı.

1. **TÜİK endeks düzeyleri ikincil kaynaktan.** 2003=100 arşivi
   `hakedis.org` üzerinden derlendi (kaynak T2), doğrudan TÜİK'ten değil.
   Aylık ve yıllık oranlar birincil kaynaklıdır (T1, T3). Katman A'nın 64/64
   sonucu, T2'nin doğru transkribe edilmiş olmasına bağlıdır.
2. **ENAG'ın Eylül-Aralık 2025 oranları tek bir ikincil kaynaktan** (E2).
   ENAG için Katman B sonucu bu dört sayıya bağımlıdır. Bu dört sayı yanlışsa
   ENAG satırı düşer. TÜİK satırı etkilenmez.
3. **Ön-kayıt bu turda kısmi.** Protokol, ham veri toplandıktan sonra ama nihai
   rapor yazılmadan önce sabitlendi. Katman A ve B'nin ilk sonuçları yazar
   tarafından görülmüştü. Tam ön-kayıt Denetim 002'den itibaren geçerlidir.
4. **ENAG'ın endeks başlangıç değeri ve sepet ağırlıkları bulunamadı.** Bu
   yüzden ENAG için Katman A ve Katman C hiç kurulamadı, sadece Katman B kuruldu.
5. **Bu denetim hiçbir kurumun ölçtüğü enflasyonun doğru olup olmadığını
   söylemez.** Sadece yayımlanan sayıların kendi içinde tutarlı olup olmadığını
   ve dışarıdan izlenebilir olup olmadığını söyler.

---

## Kaynaklar

Tam liste ve her veri hücresinin kaynak kodu: [data/SOURCES.md](data/SOURCES.md).

Başlıca birincil kaynaklar:

- TÜİK TÜFE Ağustos 2026 bülteni, **03 Eylül 2026, sayı 58290**:
  https://veriportali.tuik.gov.tr/tr/press/58290
- TÜİK baz yılı değişimi duyurusu, 30.10.2025:
  https://www.tuik.gov.tr/media/announcements/TUFE_Duyuru30102025.pdf
- TCMB, 2026 TÜFE güncellemeleri ve etkileri:
  https://www.tcmb.gov.tr/wps/wcm/connect/blog/tr/main+menu/analizler/2026+yili+tuketici+fiyat+endeksindeki+guncellemeler+ve+etkileri

---

## Sonraki tur

Denetim 002, `PROTOCOL.md` tam ön-kayıtla açılır ve şu soruyu sorar:
**iki kurumun sepetleri, kamuya açık ağırlık bilgisiyle ne kadar
örtüştürülebiliyor?** Yani bu turun cevaplayamadığı soru.
