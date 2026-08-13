# Kurulum ayrıntıları

## Gerekli araçlar

- Git
- curl
- Bash
- Python 3.14 veya üzeri
- uv (önerilir; bağımlılık kurulumu ve kalite komutları için gerekir)

## Etkileşimli kurulum

Argüman vermeden çalıştırıldığında betik, bir terminal mevcutsa hedef dizini,
paket adını ve proje adını sorar:

```bash
curl -fsSL "https://raw.githubusercontent.com/alirizagurtas/agent-template/main/install.sh?cache_bust=$(date +%s)" | bash
```

## Otomasyona uygun kurulum

CI veya terminal olmayan ortamlarda üç değeri argüman olarak ver:

```bash
curl -fsSL "https://raw.githubusercontent.com/alirizagurtas/agent-template/main/install.sh?cache_bust=$(date +%s)" | bash -s -- my-project my_package my-project-name
```

Sırasıyla hedef dizin, geçerli bir küçük harfli Python paket adı ve dağıtım
adıdır. Aynı değerler `DEST`, `PACKAGE` ve `PROJECT_NAME` ortam değişkenleriyle
de verilebilir.

Betik, hedef dizin zaten varsa işlem yapmaz. Başarılı kurulumdan sonra proje
yeni bir Git deposudur; `uv` kuruluysa bağımlılıklar ve ilk yapı indeksi de
hazırdır.
