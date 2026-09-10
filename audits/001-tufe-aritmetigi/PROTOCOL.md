> **Bu dosya, sonuçlar hesaplanmadan önce sabitlenmiştir.**
> Git geçmişi bunu doğrular: bu commit, sonuçları içeren commit'ten öncedir.
> `git log --follow audits/001-tufe-aritmetigi/` ile sıra kontrol edilebilir.

# Denetim 001. Protokol

**Konu:** TÜİK TÜFE ve ENAG E-TÜFE serilerinin iç aritmetik tutarlılığı ve
yeniden üretilebilirliği.

**Yazan:** umutseve4
**Sabitlenme tarihi:** 2026-09-10
**Veri kesim tarihi:** 2026-09-10. Her iki kurumun da son yayımlanan ayı Ağustos 2026.

---

## 1. Neyi test ediyorum

### Katman A. Endeks düzeyi ile aylık oran birbirini tutuyor mu

TÜİK hem 2003=100 endeks düzeyini hem aylık yüzde değişimi yayımlıyor.
Bu ikisi aynı sayıdan türer, dolayısıyla birbirini tutmak zorundadır.

Her ay için:

```
endeksten_oran = (endeks[t] / endeks[t-1] - 1) * 100
artık = endeksten_oran - yayımlanan_oran
```

### Katman B. Yıllık oran, on iki aylık oranın bileşiği ile aynı mı

```
bileşik = (Π (1 + aylık[i]/100) - 1) * 100
```

Pencere: Eylül 2025 - Ağustos 2026. Bu pencere kasıtlı seçildi, çünkü
TÜİK'in Ocak 2026'daki baz yılı değişimini (2003=100 -> 2025=100) ortadan keser.

Aynı test ENAG'a da uygulanır. Tek kuruma uygulanan test denetim değildir.

### Katman C. Kümülatif fiyat düzeyi

Eylül 2020 - Ağustos 2026 arası çarpan. 2026 için TÜİK 2003=100 düzeyi
yayımlamadığından seri sentetik olarak devam ettirilir ve **sentetik olduğu
her yerde yazılır**.

### Katman D. Yeniden üretilebilirlik karnesi

Sekiz ölçüt, **her iki kuruma da aynen** uygulanır.

---

## 2. Tolerans formülü

Yayımlanan sayılar iki ondalığa yuvarlanmıştır. Yuvarlama yarıçapı `h = 0,005`.

**Katman A için.** Sabit tolerans kullanmak yanlıştır, çünkü endeks düzeyi de
yuvarlıdır ve taşıdığı hata endeksin büyüklüğüne göre değişir. Gerçek endeksler
`A ∈ [a-h, a+h]` ve `B ∈ [b-h, b+h]` aralığındadır. Oranın izin verilen sınırları:

```
alt = ((a - h) / (b + h) - 1) * 100 - h
üst = ((a + h) / (b - h) - 1) * 100 + h
```

Sondaki `∓h`, yayımlanan oranın kendi yuvarlamasıdır. Bu sınırlar **her ay için
ayrı** hesaplanır.

**Katman B için.** On iki oranın her biri `±h` oynayabilir. Zarf:

```
alt = (Π (1 + (r[i] - h)/100) - 1) * 100 - h
üst = (Π (1 + (r[i] + h)/100) - 1) * 100 + h
```

Sondaki `∓h` yayımlanan yıllık oranın yuvarlamasıdır.

Tüm hesaplar Python `Decimal`, 50 basamak hassasiyet. İkili kayan nokta yok.

---

## 3. PASS / FAIL eşikleri

| Katman | PASS | FAIL |
|---|---|---|
| A | 64 ayın tamamı kendi tolerans aralığında | bir ay bile dışında |
| B | bileşik, zarfın içinde | zarfın dışında |
| C | eşik yok, tanımlayıcı | - |
| D | eşik yok, karne | - |

---

## 4. Önceden ilan edilen yorum sınırları

Bu satırlar sonuç ne çıkarsa çıksın raporda yer alacak.

1. Katman A ve B **özdeşlik kontrolüdür**. Yıllık oran aynı endeksten türediği
   için ara terimler sadeleşir. Bu testler kopyalama hatasını, zincirleme
   hatasını ve kaba tutarsızlığı yakalar. **Fiyat derlemesinin, sepetin,
   ağırlıkların, kalite düzeltmesinin veya ölçülen enflasyonun doğruluğunu
   sınamaz.**
2. Katman B, baz yılı değişiminin **etkisini** ölçmez. Bunun için örtüşme
   dönemi, aynı mikro fiyatlar üzerinde eski/yeni ağırlık karşılaştırması ve
   resmî bağlantı katsayıları gerekir. Bunlar kamuya açık değildir.
3. Bir sitenin belirli bir anda erişilemez olması **kalıcı yokluk kanıtı
   değildir**. Katman D'de kullanılacak ifade "erişemedik", "yoktur" değil.
4. Katman C'deki Ağustos 2026 endeksi TÜİK tarafından yayımlanmamıştır.
   Türetilmiştir ve belirsizlik bandıyla birlikte verilecektir.
5. İki kuruma farklı standart uygulanmayacak. Bir kuruma uygulanan test
   diğerine de uygulanabiliyorsa uygulanacaktır.

---

## 5. Sonuç ne çıkarsa çıksın yayımlama taahhüdü

Dört olası sonucun dördü de aynı yerde, aynı biçimde yayımlanır:

| | ENAG geçer | ENAG kalır |
|---|---|---|
| **TÜİK geçer** | yayımlanır | yayımlanır |
| **TÜİK kalır** | yayımlanır | yayımlanır |

Başlık, sonuç görüldükten sonra seçilmeyecek şekilde bu tablodan türetilir.

---

## 6. Bu protokolün bilinen zayıflığı

Denetim 001 için ön-kayıt **kısmidir**. Protokol, ham veri toplandıktan sonra
ancak nihai rapor yazılmadan önce sabitlenmiştir. Katman A ve B'nin ilk
sonuçları yazar tarafından görülmüştür; QA incelemesi sonrası tolerans formülü
düzeltilmiş ve simetri gereği ENAG testi eklenmiştir.

Tam ön-kayıt Denetim 002'den itibaren geçerlidir: protokol, veriye
dokunulmadan önce commit edilecektir.

Bu zayıflığı gizlemek yerine yazmak, protokolün kendisinin bir parçasıdır.
