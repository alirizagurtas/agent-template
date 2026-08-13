# AGENTS.md

## Kesin kurallar

1. `raise` içinde doğrudan f-string kullanma. Mesajı önce bir değişkene ata,
   ardından proje-özel exception'ı fırlat.
2. Test yardımcıları dahil hiçbir fonksiyon imzasında `Any` taşıma. Belirsiz
   yükleyici dönüşlerini sınırda `cast(object, ...)` ve `isinstance` ile daralt.
3. `object` tipindeki bir sözlüğün anahtarlarını kontrol etmeden önce değeri
   `dict[object, object]` tipine cast et.
4. `set().union(*generator)` kullanma. `set[T]` oluştur ve düz bir döngüde
   `update` çağır.
5. `argparse.Namespace` döndürme veya attribute'larına cast etmeden erişme.
   Argümanları typed ilkel değerlere dönüştür.
6. Script'leri `importlib.util` ile dinamik yükleme; her zaman ayrı süreçte
   çalıştırarak test et.
7. `src/` ve `scripts/` altında, `len()` karşılaştırmaları dahil her sayısal
   karşılaştırma değerini modül seviyesinde `UPPER_SNAKE_CASE` sabit yap.
8. Fonksiyon başına en fazla sekiz dallanma ve altı `return` kullan. Mantığı
   önceden isimlendirilmiş tek sorumluluklu yardımcı fonksiyonlara böl.
9. Importları stdlib, third-party ve local olarak; her grup içinde alfabetik
   sırala. Kullanılmayan import bırakma.
10. Bağımsız gereksinimler için ayrı test yaz. İkiden fazla ilgisiz senaryoyu
    tek testte birleştirme.
11. Boolean parametreleri keyword-only yap. Pozisyonel boolean gönderme.
12. Yerleşik genel amaçlı exception yerine modüle ait özel bir exception sınıfı
    kullan.
13. Çıplak `except` veya `except Exception` kullanma; yalnız somut hata
    türlerini yakala.

## Genel kurallar

- Proje, paket veya kaynak/test yollarını hardcode etme; bunları
  `project_structure.yaml` dosyasından oku.
- Değişikliği istenen implementasyon ve test kapsamıyla sınırlı tut.
  Açıkça istenmedikçe bağımlılıkları, araçlandırmayı veya ilgisiz dosyaları
  değiştirme.
- Dosya G/Ç'sinde UTF-8 kullan ve depo içeriğini İngilizce yaz; yalnız açıkça
  Türkçe yerelleştirme istenen kullanıcı dokümantasyonu istisnadır.

## Doğrulama sırası

Python kodunu değiştirdikten sonra şu komutları sırayla çalıştır:

```bash
uv run --locked ruff check --fix <değişen-dosyalar>
uv run --locked ruff format <değişen-dosyalar>
uv run --locked poe test-target <path-or-node-id>
uv run --locked poe check
```

`uv run --locked poe test-integration` komutunu yalnız değişiklik bir
entegrasyon sınırını etkilediğinde çalıştır. Varsayılan `poe check` akışını
değiştirme.

## Proje yapısı indeksi

`project_structure.yaml`, bir domain'in yolunu, testlerini ve doğrudan domain
bağımlılıklarını gösteren kaynak gerçektir. Bu bilgiler için depoyu taramadan
önce indeksi oku. Davranış veya API gerektiğinde ilgili kaynak kodunu okumayı
ihmal etme.

Kaynak domain'leri, indekslenen testler veya domain importları değiştiğinde:

```bash
uv run --locked poe sync-project-structure
```

Bu komutu son kalite kapısından önce çalıştır. `domains` alanını elle
düzenleme; bu alan yalnız sync betiğinin sorumluluğundadır. `version`,
`package` ve `paths` alanları ise elle yönetilen yapılandırmadır.
