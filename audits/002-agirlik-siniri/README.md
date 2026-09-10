# Denetim 002. Ağırlıklar tek başına farkı üretebilir mi?

**Dönem:** Ağustos 2026. **Yayım:** 2026-09-10.
**Ön kayıt:** [`PROTOCOL.md`](PROTOCOL.md), veri çekilmeden önce ve tek başına
commit edildi (`4b1e27f`). Sıra `git log --reverse` ile doğrulanabilir ve bir
testle zorunlu tutulur.

## Tek cümle

**Denetim durdu, çünkü kendi hipotezim yanlış çıktı.** Ön kayıtta yazdığım
Katman A özdeşliği (13 grup ağırlığının 13 grup yıllık oranıyla ağırlıklı
ortalaması manşeti verir) tutmuyor: hesaplanan **%31,278154**, yayımlanan
**%31,51**, artık **-0,231846 puan**, yuvarlama zarfının **15,29 katı**.
Protokoldeki durdurma kuralı 1 gereği Katman B ve Katman C hesaplanmadı ve
yayımlanmadı.

Bu bir TÜİK hatası değildir. Aşağıda gösterildiği gibi TÜİK'in kendi
yayımladığı katkılar manşete tam olarak toplanıyor. Kırılan şey, benim
kurduğum toplulaştırma modelidir.

## Neden bu soru soruldu

Denetim 001 şunu bulmuştu: TÜİK ile ENAG arasındaki fark aritmetik hatadan
gelmiyor, sepetten geliyor. 001 bunu adlandırdı ama ölçmedi. 002 ölçme
denemesiydi.

Ölçmeden önce kaynak yapısı tarandı ve şu çıktı, protokole `BULGU-0` olarak
yazıldı: TÜİK 13 ana grup için ağırlık, endeks, aylık ve yıllık oran ve katkı
yayımlıyor; ENAG aynı ay için kamuya açık olarak yalnızca tek bir genel aylık
ve tek bir genel yıllık oran yayımlıyor. Grup kırılımı, ağırlık tablosu,
endeks düzeyi ve baz yılı bulunamadı. İki taraflı bir dağıtım için iki taraflı
kırılım gerekir. Bu yüzden soru, tek taraflı veriyle tam olarak
hesaplanabilen bir biçime çevrildi: **TÜİK'in kendi grup oranları sabitken,
ağırlıklar tek başına ENAG'ın manşetine ulaşabilir mi?**

O soruya bu turda cevap verilmedi. Çünkü ona geçmeden önce yapılması gereken
ön test başarısız oldu.

## Katman A. Kesit toplulaştırma özdeşliği

```
r_hesaplanan = toplam(w_i * r_i) / toplam(w_i)
```

| büyüklük | değer |
|---|---:|
| Hesaplanan yıllık oran | %31,278154 |
| Yayımlanan yıllık oran | %31,51 |
| **Artık** | **-0,231846 puan** |
| Zarf alt sınırı | %31,262992 |
| Zarf üst sınırı | %31,293318 |
| Zarf yarı genişliği | 0,015163 puan |
| Yayımlanan değer zarfın içinde mi | **Hayır** |
| En yakın sınıra uzaklık | 0,216682 puan |
| Artık / zarf yarı genişliği | **15,29 kat** |
| Sonuç | **KIRILDI** |

Zarf sabit alınmadı. Hem ağırlıklar hem oranlar iki ondalıkla yayımlandığı
için her hücreye h = 0,005 yarı genişlik verildi ve protokoldeki işaret
seçimiyle en kötü durum arandı: üst sınır için oranı ortalamanın üstünde olan
gruplara +h, altında olanlara -h; alt sınır için tersi. Yayımlanan manşet de
yuvarlanmış olduğundan sonuca ayrıca h eklendi.

Yani bu sonuç yuvarlamayla açıklanamıyor. Zarfı en cömert haliyle kursak bile
manşet dışarıda kalıyor ve 15 kat uzakta.

## Durdurma kuralları

| kural | durum | gerekçe |
|---|---|---|
| 1. Katman A kırılırsa denetim durur | **ATEŞLENDİ** | Artık zarfın dışında. Katman B ve C yayımlanmadı. |
| 2. Ağırlık toplamı yuvarlama payından fazla saparsa dur | ATEŞLENMEDİ | Toplam 99,97, sapma -0,03, pay 13 x 0,005 = 0,065. |
| 3. Herhangi bir grup için veri bulunamazsa dur | ATEŞLENMEDİ | 13 grubun tamamı için ağırlık, oran ve katkı bulundu. |
| 4. H2 yalanlanmazsa soru değiştirilmez | Uygulanamadı | Katman B hiç çalıştırılmadı. |

Durdurma kuralı 1 `audit.py` içinde kodla uygulanmıştır. Katman B ve Katman C
fonksiyonları bu dosyada **bilerek yoktur**. Yani "hesapladım ama
yayımlamadım" değil, hesaplanmadı.

Neden böyle: kırık bir özdeşliğin üstüne kurulan sınır argümanı geçersizdir.
`toplam(w_i * r_i) / toplam(w_i)` ifadesi TÜİK'in manşetini üretmiyorsa, aynı
ifadenin dışbükey birleşim sınırına dayanan "ENAG'ın oranına ulaşılamaz"
sonucu da dayanaksızdır. Sonucu yayımlamak, kendi testimin kırıldığını
görmezden gelmek olurdu.

## Tanı notu (PROTOKOL DIŞI)

**Bu bölüm sonuç görüldükten sonra eklenmiştir ve hiçbir hipotezi
doğrulamaz.** Ön kayıtta yoktur, dolayısıyla onaylayıcı kanıt değildir.
Yalnızca "Katman A neden kırıldı" sorusuna dair bir gözlemi kayda geçirir.

TÜİK'in yayımladığı 13 yıllık katkı toplanınca **tam olarak 31,51 puan**
çıkıyor, artık 0,000000. Yani veri iç tutarlı ve yanlış aktarılmamış.
Kırılma, aktarım hatasından değil, H1'in yanlış bir toplulaştırma modeli
olmasından geliyor: yıllık manşet, cari yıl ağırlıklarının basit ağırlıklı
ortalaması değildir. Katkılar, yıl içinde fiyat hareketiyle güncellenmiş
etkin ağırlıkları taşır.

Katkılardan ima edilen etkin ağırlık `w_eff_i = k_i / r_i * 100`:

| grup | yayımlanan ağırlık | ima edilen etkin ağırlık | fark |
|---|---:|---:|---:|
| Gıda ve alkolsüz içecekler | 24,44 | 24,03 | -0,41 |
| Alkollü içecekler ve tütün | 2,75 | 2,96 | +0,21 |
| Giyim ve ayakkabı | 7,90 | 5,32 | **-2,58** |
| Konut, su, elektrik, gaz ve diğer yakıtlar | 11,40 | 12,60 | +1,20 |
| Mobilya ve ev eşyaları | 7,92 | 7,93 | +0,01 |
| Sağlık | 2,79 | 3,01 | +0,22 |
| Ulaştırma | 16,62 | 16,93 | +0,31 |
| Bilgi ve iletişim | 3,10 | 3,47 | +0,37 |
| Eğlence, dinlence, spor ve kültür | 4,34 | 4,05 | -0,29 |
| Eğitim hizmetleri | 2,02 | 2,13 | +0,11 |
| Lokantalar ve konaklama hizmetleri | 11,13 | 10,69 | -0,44 |
| Sigorta ve finansal hizmetler | 1,07 | 1,28 | +0,21 |
| Kişisel bakım, sosyal koruma ve çeşitli mal ve hizmetler | 4,49 | 4,36 | -0,13 |
| **toplam** | **99,97** | **98,7576** | |

En büyük negatif sapma giyim ve ayakkabıda: yayımlanan ağırlık 7,90, ima
edilen etkin ağırlık 5,32. Etkin ağırlık toplamının 100 olmaması da bu
gözlemin kendi sınırıdır ve düzeltilmemiştir.

Bu tablo bir bulgu değil, bir sonraki turun girdisidir. Yorumlanmadı.

## Kendi zaafları

1. **13 grubun ağırlık, oran ve katkı değerlerinin tamamı ikincil
   kaynaktandır** (kod S1, BMD). TÜİK'in Ek Tablo-1 ve Ek Tablo-3 dosyalarına
   bu çalışmada kullanılan araç zinciriyle doğrudan erişilemedi. Sekiz hücre
   birincil bültenle (kod P1) karşılaştırıldı ve birebir uyuştu, ama bu
   tablonun tamamını doğrulamaz. Katman A'nın kırıldığı sonucu, S1'in doğru
   aktarılmış olmasına bağımlıdır.
2. Bunun karşı kanıtı şudur ve zayıf değildir: S1'deki 13 katkı tam olarak
   31,51'e toplanıyor. Rastgele bir aktarım hatası bu toplamı bozardı. Yine de
   bu, sistematik bir hatayı dışlamaz.
3. Denetim tek aya bakmaktadır. Katman A'nın başka aylarda da kırılıp
   kırılmadığı test edilmemiştir. Tek ay, bir örüntü değil bir gözlemdir.
4. H1'in yanlış kurulmuş olması benim hatamdır, TÜİK'in değil. Protokolü
   yazarken TÜİK'in yıllık toplulaştırmasının cari yıl ağırlıklarının basit
   ağırlıklı ortalaması olduğunu varsaydım ve bu varsayımı ön kayıtta ayrı
   bir madde olarak sınamadım.
5. Bu denetim ENAG'ın oranının doğru ya da yanlış olduğunu **test etmez**.
   Bu turda ENAG orani üzerine hiçbir hesap kurulmamıştır.

## Yeniden üretim

```
python3 audits/002-agirlik-siniri/audit.py --json --check
```

`--check`, raporda geçen 21 sayının tamamını `data/tuik-2026-08-ana-gruplar.csv`
dosyasından yeniden hesaplar ve `audit.py` içindeki `BEYAN` sözlüğüyle
karşılaştırır. Tek bir sapma çıkış kodunu 1 yapar ve CI kırılır.

Koruma iddia ile değil, gerçek bir kırılmayla kanıtlanmıştır. Bkz. aşağıdaki
kanıt zinciri bölümü.

## Kanıt zinciri

| adım | kanıt |
|---|---|
| Protokol veriden önce, tek başına commit edildi | `4b1e27f`, `git log --reverse -- audits/002-agirlik-siniri/` |
| Bu sıra bir testle zorunlu | `tests/test_audit_002.py::test_protokol_veriden_once_commit_edilmis` |
| Rapordaki her sayı ham veriden üretiliyor | `audit.py --check`, 21 beyan |
| Veri bozulursa kontrol kırılıyor | `tests/test_audit_002.py::test_mutasyon_kontrolu_kirar` |
| Durdurma kuralı 1 kodda uygulanmış | `audit.py`, Katman B ve C fonksiyonları yok, test bunu doğruluyor |
| Kaynaklar hücre bazında kodlanmış | [`data/SOURCES.md`](data/SOURCES.md) |

## Sonraki tur için bırakılan soru

Ön kayıtta sorulan soru cevapsız kaldı ve **değiştirilmedi**. Denetim 003, doğru
toplulaştırma özdeşliğini (katkı temelli, etkin ağırlıklı) ön kayda yazıp
Katman B'yi o temelin üstüne kurmalıdır. 002'nin tanı notundaki etkin ağırlık
tablosu o turun girdisidir, sonucu değildir.

---

Denetim 001: [`../001-tufe-aritmetigi/`](../001-tufe-aritmetigi/)
