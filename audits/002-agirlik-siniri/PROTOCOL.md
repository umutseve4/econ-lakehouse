# Denetim 002. Ön kayıt protokolü

**Bu dosya, sayısal veri çekilmeden önce ve tek başına commit edilmiştir.**
Sıra, `git log --reverse -- audits/002-agirlik-siniri/` ile ve
`tests/test_audit_002.py` içindeki bir testle doğrulanır. Aşağıdaki hipotez,
eşikler ve durdurma kuralı, sonuçlar görülmeden yazılmıştır.

Denetim 001 kapattığı soruyu şöyle bıraktı: TÜİK ile ENAG arasındaki fark
aritmetik hatadan gelmiyor, sepetten geliyor. 001 bunu **adlandırdı ama
ölçmedi**. 002 ölçme denemesidir.

## 0. Kapsam kararı ve neden soru değiştirildi

İlk niyet, iki kurumun sepetlerini ana harcama grubu düzeyinde yan yana koyup
farkı gruplara dağıtmaktı (issue #90). Protokol yazılmadan önce yalnızca
**kaynak yapısı** tarandı, hiçbir sayısal değer okunmadı. Tarama şunu gösterdi:

- TÜİK, Ağustos 2026 için 13 ana harcama grubunun ağırlıklarını, endekslerini,
  aylık ve yıllık değişim oranlarını ve genel endekse katkılarını yayımlıyor.
- ENAG, aynı ay için kamuya açık olarak yalnızca **tek bir genel aylık ve tek
  bir genel yıllık oran** yayımlıyor. Grup kırılımı, ağırlık tablosu, endeks
  düzeyi ve baz yılı bulunamadı.

Bu asimetri, planlanan grup bazlı ayrıştırmayı **kurulamaz** kılar. İki taraflı
bir dağıtım için iki taraflı kırılım gerekir. Bu bulgunun kendisi kayda geçer
(aşağıda `BULGU-0`) ve soru, kamuya açık veriyle **tam olarak hesaplanabilen**
bir biçime çevrilir:

> **Ağırlıklar tek başına bu farkı üretebilir mi?**

Yani: TÜİK'in kendi yayımladığı 13 grup oranı sabit tutulduğunda, ağırlıkları
nasıl dağıtırsak dağıtalım manşet oranı ENAG'ın açıkladığı düzeye
çıkarılabilir mi? Bu soru tek taraflı veriyle cevaplanabilir ve cevabı iki
yönde de kesindir.

## 1. Hipotezler

- **H1 (toplulaştırma özdeşliği):** TÜİK'in yayımladığı manşet yıllık oran,
  yine TÜİK'in yayımladığı 13 grup ağırlığı ve 13 grup yıllık oranından
  ağırlıklı ortalama olarak yeniden üretilebilir.
- **H2 (ağırlık sınırı):** ENAG'ın manşet yıllık oranı, TÜİK'in grup oranları
  sabitken herhangi bir ağırlık dağılımıyla elde edilebilir.

H2 kasten "elde edilebilir" yönünde kurulmuştur, yani denetim onu yalanlamaya
çalışır. Yalanlanırsa sonuç güçlüdür; yalanlanamazsa da yayımlanır.

## 2. Yöntem

### Katman A. Toplulaştırma özdeşliği (H1)

Ağırlıklar `w_i`, grup yıllık oranları `r_i`, i = 1..13 olmak üzere:

```
r_hesaplanan = toplam(w_i * r_i) / toplam(w_i)
```

`artik = r_hesaplanan - r_yayimlanan`.

Tolerans sabit alınmaz. Hem ağırlıklar hem oranlar yuvarlanmış yayımlanır.
Her `w_i` ve her `r_i` için yarı genişlik `h_w` ve `h_r`, yayımlanan ondalık
basamak sayısından türetilir (iki ondalık ise 0,005). Zarf, her iki yönde de
en kötü durum aranarak hesaplanır:

```
ust = maks( toplam((w_i + s_i*h_w) * (r_i + h_r)) / toplam(w_i + s_i*h_w) )
alt = min ( toplam((w_i + s_i*h_w) * (r_i - h_r)) / toplam(w_i + s_i*h_w) )
```

`s_i` işaret seçimi doğrudan aranır: ağırlık sapması yalnızca oran farklılaşması
üzerinden etkilidir, bu yüzden üst sınır için oranı ortalamanın üstünde olan
gruplara `+h_w`, altında olanlara `-h_w` verilir; alt sınır için tersi. Sonuca
`h_r` eklenir çünkü `r_yayimlanan` da yuvarlanmıştır.

**Not:** Bu, Denetim 001'de yapılmayan bir testtir. 001 zaman serisi
özdeşliğini (ardışık endeks düzeylerinden aylık oran) test etti. 002 kesit
özdeşliğini (aynı ayın grup oranlarından manşet oran) test eder. İkisi farklı
özdeşliklerdir ve biri geçerken diğeri kırılabilir.

### Katman B. Ulaşılabilir aralık (H2)

Ağırlıklar negatif olamaz ve toplamı sabittir. Bu kısıt altında ağırlıklı
ortalama, grup oranlarının **dışbükey birleşimidir**. Dolayısıyla:

```
ulasilabilir_aralik = [ min(r_i) , maks(r_i) ]
```

Uç noktalar, tüm ağırlığın tek bir gruba verilmesine karşılık gelir. Test:

- `r_ENAG > maks(r_i)` ise, TÜİK'in grup oranları veri kabul edildiğinde
  ENAG'ın manşetine **hiçbir ağırlık dağılımıyla** ulaşılamaz. H2 yalanlanır.
- `r_ENAG` aralığın içindeyse H2 yalanlanamaz ve denetim, farkın ağırlıkla
  açıklanabilir olduğunu **dışlayamaz**. Bu durumda gereken yeniden dağıtımın
  büyüklüğü Katman C'de ölçülür.

Yuvarlama zarfı burada da uygulanır: karşılaştırma `maks(r_i) + h_r` ile
`r_ENAG - h_r` arasında yapılır, yani sınır ENAG lehine gevşetilir. Yalanlama
ancak bu gevşek sınırda bile aşılamıyorsa ilan edilir.

### Katman C. Tek grup taşıma yükü

Fark bütçesi `D = r_ENAG - r_TUIK`. Yalnızca `i` grubunun oranı değişerek fark
kapanacaksa gereken oran:

```
r_i_gerekli = r_i + D * (toplam(w) / w_i)
```

Her grup için `r_i_gerekli` ve bunun mevcut orana göre kaç katı olduğu
yazılır. Bu tablo, hangi grupların düşük ağırlıkları nedeniyle farkı tek
başına taşımasının aritmetik olarak absürt olduğunu gösterir. Yorum
yapılmaz, sayı verilir.

### Katman D. Yeniden üretilebilirlik notu

Denetim 001'deki 8 maddelik karne, 002'nin kullandığı veri kalemleri için
tekrarlanır. Yeni bir puan icat edilmez, 001'in maddeleri aynen uygulanır.

## 3. Durdurma kuralı

1. **Katman A kırılırsa denetim durur.** Yani TÜİK'in kendi kesit özdeşliği
   zarfın dışına çıkarsa, bulgu budur ve Katman B ile C yayımlanmaz. Kırık bir
   özdeşliğin üstüne kurulan sınır argümanı geçersizdir.
2. Ağırlıkların toplamı yayımlanan toplamdan (1000 veya 100) yuvarlama
   payından fazla saparsa, veri hatalı okunmuş sayılır ve denetim durur.
3. 13 gruptan herhangi biri için ağırlık ya da oran bulunamazsa, eksik grup
   gizlenmez; denetim durur ve eksik kalem adıyla rapor edilir.
4. Sonuç H2'yi yalanlamazsa soru değiştirilmez. "Ağırlık farkı bu farkı
   üretebilir" sonucu da aynı ayrıntıyla yayımlanır.

## 4. Kabul kriterleri

- Rapordaki her sayı `audit.py` tarafından ham CSV'den yeniden hesaplanır;
  `--check` sapma bulursa çıkış kodu 1.
- Her veri hücresinin `data/SOURCES.md` içinde bir kodu ve URL'si vardır.
  İkincil kaynaklar açıkça ikincil işaretlenir.
- Raporun kendi zaafları bölümü vardır.
- CI koruması gerçek bir kırılmayla kanıtlanır.
- Uzun tire kullanılmaz.

## 5. Baştan kabul edilen sınırlar

- **BULGU-0:** ENAG Ağustos 2026 için grup kırılımı, ağırlık tablosu, endeks
  düzeyi ve baz yılı yayımlamamaktadır. Bu nedenle farkın gruplara dağıtılması
  kamuya açık veriyle **kurulamaz**. 002 bu boşluğu tahminle doldurmaz.
- 002, ENAG'ın oranının doğru ya da yanlış olduğunu **test etmez**. Yalnızca
  TÜİK'in grup yapısı veri kabul edildiğinde ağırlıkların ne kadarını
  açıklayabileceğini ölçer.
- Katman B, TÜİK'in grup oranlarını girdi kabul eder. Bu oranların kendisi
  tartışmalıysa Katman B'nin sonucu da o tartışmaya bağımlıdır. Bu bir kusur
  değil, sonucun okunma koşuludur ve raporda aynen yazılacaktır.
- Ağırlıklar yıllık sabittir, oranlar 12 aylık değişimdir. Yani ağırlık yapısı
  dönem başına, oranlar döneme aittir. Bu, TÜİK'in kendi yönteminin bir
  özelliğidir ve Katman A'daki artığın bir kısmını açıklayabilir. Artık zarfın
  içinde kalırsa bu etki ölçülemeyecek kadar küçüktür, dışına çıkarsa durdurma
  kuralı 1 işler.
