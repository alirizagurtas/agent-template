# Agent Template

Kodlama ajanlarıyla geliştirilen Python projeleri için sade ve yeniden
kullanılabilir başlangıç şablonu. Şablon; katı tip denetimi, hedefli test
akışı, otomatik proje yapısı indeksi ve isteğe bağlı agent değerlendirme
harness'ı sağlar.

## İçerik

- `AGENTS.md` — kodlama, test, tip daraltma ve doğrulama kuralları.
- `project_structure.yaml` — domain yolları, testleri ve domain bağımlılıkları
  için makine-okunur indeks.
- `scripts/sync_project_structure.py` — indeksi gerçek kaynak koddan ve
  testlerden deterministik biçimde üretir.
- `scripts/run_harness.sh` — aynı prompt'u temiz bir Git başlangıcında çoklu
  kez çalıştırarak agent davranışındaki varyasyonu ölçer.
- `scripts/harness_stats.py` — harness JSONL kayıtlarını CSV ve terminal
  özetine dönüştürür.

## Gereksinimler

Kurulum için `git`, `curl` ve Bash gerekir. Python bağımlılıklarını kurmak ve
kalite komutlarını çalıştırmak için [uv](https://docs.astral.sh/uv/) kurulu
olmalıdır.

## Kurulum

Yeni projeyi tek komutla oluştur:

```bash
curl -fsSL "https://raw.githubusercontent.com/alirizagurtas/agent-template/main/install.sh?cache_bust=$(date +%s)" | bash -s -- my-project
```

Bu komut `my-project/` dizinini ve varsayılan `agent_project` Python paketini
oluşturur. Hedef dizini, paket adını ve dağıtım/proje adını birlikte vermek
için en fazla üç argüman kullanabilirsin:

```bash
curl -fsSL "https://raw.githubusercontent.com/alirizagurtas/agent-template/main/install.sh?cache_bust=$(date +%s)" | bash -s -- my-project my_package my-project-name
```

Kurulum betiği yer tutucuları günceller, yeni bir Git deposu başlatır ve `uv`
varsa bağımlılıkları kurup proje yapısı indeksini üretir.

## Yeni proje sonrası

1. Proje dizinine gir: `cd my-project`.
2. `pyproject.toml` içindeki proje açıklamasını ve uygulama bağımlılıklarını
   ihtiyaçlarına göre düzenle.
3. Kaynak kodunu `src/<paket_adı>/` altında, testleri `tests/unit/` altında
   ekle.
4. Kodlama ve doğrulama kurallarını uygulamadan önce `AGENTS.md` dosyasını oku.
5. Domain, domain testi veya domain bağımlılığı eklediğinde indeksi güncelle.

## Günlük komutlar

| Amaç | Komut |
| --- | --- |
| Bağımlılıkları kur veya güncelle | `uv sync` |
| Hedefli test çalıştır | `uv run --locked poe test-target <path-or-node-id>` |
| Birim testlerini çalıştır | `uv run --locked poe test-unit` |
| Entegrasyon testlerini çalıştır | `uv run --locked poe test-integration` |
| Yapı indeksini güncelle | `uv run --locked poe sync-project-structure` |
| Tüm kalite kapısını çalıştır | `uv run --locked poe check` |
| Harness başlat | `uv run --locked poe run-harness <prompt-file> HEAD "uv run --locked poe check" 5` |

`poe check`; lint, format denetimi, Basedpyright, birim testleri ve proje
yapısı indeksinin güncelliğini doğrular. Entegrasyon testleri varsayılan kalite
kapısına dahil değildir; yalnız değişiklik gerçekten bir entegrasyon sınırını
etkilediğinde çalıştırılmalıdır.

## Proje yapısı indeksi

`project_structure.yaml`, her domain'in kaynak yolunu, domain testlerini ve
diğer domain'lere doğrudan bağımlılıklarını saklar. `domains` alanını elle
düzenleme; yalnız `sync-project-structure` görevi üretmelidir. `version`,
`package` ve `paths` alanları ise proje yapılandırmasıdır ve gerektiğinde elle
güncellenebilir.

## Harness

Harness, aynı geliştirme isteğinin farklı agent koşularındaki sonuçlarını
ölçmek içindir. Her koşudan önce çalışma ağacını belirtilen Git referansına
geri alır ve sonuçları `harness_runs/` altına yazar.

```bash
uv run --locked poe run-harness prompts/feature.txt main "uv run --locked poe check" 5
```

Bu araç `git reset --hard` ve `git clean -fd` kullandığı için yalnız kaybetmeyi
göze aldığın değişiklikleri içeren, commit'lenmiş bir başlangıçta çalıştır.
Harness isteğe bağlıdır ve normal `poe check` akışının parçası değildir.

## Temel ilke

Ajanın bir kuralı hatırlamasına güvenme; kuralı doğrulanabilir hale getir.
Tekrarlanan yapısal bilgileri `project_structure.yaml` ile, kalite beklentisini
ise otomatik testler ve `poe check` ile denetlenebilir kıl.
