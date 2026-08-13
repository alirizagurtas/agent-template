# AGENTS.md

## Kesin kurallar

Bunlar tercih değil, zorunluluktur. Her biri, bu depoda gerçek oturumlarda
tekrar eden ve ölçülmüş bir hata zincirini kökten kapatmak için var. "Yaz,
sonra düzelt" değil — bu kalıba hiç girme.

1. **Exception mesajı asla f-string literal olarak `raise` içine yazılmaz.**
   Her zaman önce değişkene ata, sonra `raise` et.
   ```python
   # Yanlış
   raise ConfigurationError(f"Invalid YAML in {config_path}: {error}")

   # Doğru
   message = f"Invalid YAML in {config_path}: {error}"
   raise ConfigurationError(message)
   ```

2. **`Any` tipi asla fonksiyon imzasına taşınmaz — production kodunda
   (`scripts/`, `src/`) olduğu kadar test yardımcı fonksiyonlarında
   (`tests/`) da geçerlidir.**
   `yaml.safe_load`, `json.load` ve benzeri belirsiz dönüşleri her zaman
   sınırda (`cast(object, ...)` + `isinstance`) daralt. Bu kural üç kez
   yalnız `scripts/` içinde uygulanıp `tests/` içindeki YAML okuma yardımcı
   fonksiyonlarında (`load_domains`, `read_domains` gibi) unutuldu — production
   kodunda `cast` kullandın diye testte muaf sayma, `yaml.safe_load`'un dönüş
   tipi nerede çağrılırsa çağrılsın `Any`'dir.
   ```python
   # Yanlış (scripts/ içinde)
   def load_config(path: Path) -> dict[str, Any]: ...

   # Doğru (scripts/ içinde)
   def load_config(path: Path) -> dict[str, object]:
       loaded = cast(object, yaml.safe_load(path.read_text()))
       if not isinstance(loaded, dict):
           message = "Configuration must be a YAML mapping."
           raise ConfigurationError(message)
       ...

   # Yanlış (tests/ içindeki bir test yardımcı fonksiyonu — aynı hata)
   def load_domains(config_path: Path) -> dict[str, object]:
       loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
       assert isinstance(loaded, dict)
       return loaded["domains"]

   # Doğru (tests/ içinde)
   def load_domains(config_path: Path) -> dict[str, object]:
       loaded = cast(object, yaml.safe_load(config_path.read_text(encoding="utf-8")))
       assert isinstance(loaded, dict)
       configuration = cast(dict[object, object], loaded)
       domains = configuration["domains"]
       assert isinstance(domains, dict)
       return cast(dict[str, object], domains)
   ```

3. **`object` tipinde bir `dict`'in anahtarları asla doğrudan `isinstance` ile taranmaz.**
   Her zaman önce `cast(dict[object, object], value)` yap, sonra anahtarları kontrol et.
   ```python
   # Yanlış
   if not all(isinstance(key, str) for key in value):
       ...
   return cast(dict[str, object], value)

   # Doğru
   mapping = cast(dict[object, object], value)
   if not all(isinstance(key, str) for key in mapping):
       ...
   return cast(dict[str, object], mapping)
   ```

4. **`set().union(*generator_ifadesi)` kalıbı asla kullanılmaz.**
   Her zaman boş `set[T]` tanımla ve düz bir `for` döngüsüyle `update` et.
   ```python
   # Yanlış
   dependencies = set().union(
       *(dependencies_for_file(path, root, package) for path in files)
   )

   # Doğru
   dependencies: set[str] = set()
   for path in files:
       dependencies.update(dependencies_for_file(path, root, package))
   ```

5. **`argparse.Namespace` asla fonksiyon dönüşünde dışarı sızdırılmaz, ve
   hiçbir `Namespace` attribute'u asla doğrudan (cast'siz) okunmaz.**
   `namespace.write`, `namespace.check` gibi her erişim BasedPyright'ta
   `Any` (`reportAny`) döner — bu bir uyarı değil, kesin bir tip hatasıdır.
   Attribute'u okurken her zaman doğrudan `cast(bool, ...)` /
   `cast(str, ...)` uygula; asla `bool(namespace.write)` gibi çıplak
   dönüşüm veya `"--write" in sys.argv` gibi manuel ayrıştırma kalıbına
   geri düşme.
   ```python
   # Yanlış — reportAny hatası verir
   def parse_arguments() -> bool:
       return bool(parser.parse_args().write)

   # Yanlış — argparse'ı bypass eder, asla kullanma
   def parse_arguments() -> bool:
       parser.parse_args()
       return "--write" in sys.argv[1:]

   # Doğru
   def parse_arguments() -> bool:
       namespace = parser.parse_args()
       return cast(bool, namespace.write)
   ```

6. **Test edilecek script asla `importlib.util` ile modül olarak dinamik yüklenmez.**
   Bu kalıp `sys.modules` kayıt sorunlarına ve script'in dönüş tipini
   tanımlamak için gereksiz `Protocol` + zincirleme `cast` kullanımına yol
   açar. Script'i her zaman ayrı bir süreç olarak çalıştır ve `stdout`,
   `returncode` veya değişen dosya içeriği üzerinden doğrula.
   ```python
   # Yanlış
   specification = importlib.util.spec_from_file_location("script", script_path)
   module = importlib.util.module_from_spec(specification)
   specification.loader.exec_module(module)
   sync_project_structure = cast(SyncProjectStructure, cast(object, module))

   # Doğru
   result = subprocess.run(
       [sys.executable, str(script_path), "--write"],
       cwd=project_root,
       capture_output=True,
       text=True,
       check=False,
   )
   assert result.returncode == 0
   ```

7. **Karşılaştırmada kullanılan sabit sayısal değer `scripts/` ve `src/`
   içinde asla inline yazılmaz — `len(...)` karşılaştırmaları da dahil.**
   `pyproject.toml` bu kuralı yalnız `tests/**/*.py` için muaf tutar
   (`per-file-ignores: "tests/**/*.py" = ["PLR2004"]`); yani testte inline
   sayı kullanmak Ruff hatası vermez ve gereksiz sabit tanımlamaya gerek
   yoktur. Ama `scripts/` ve `src/` içindeki her karşılaştırma, N ne olursa
   olsun (2 dahil, önceki bir denemede "0,1,2 hariç" istisnası tam da bu
   yüzden yanlış çıkmıştı), modül seviyesinde `UPPER_SNAKE_CASE` bir isimle
   tanımlanır.
   ```python
   # Yanlış (scripts/ veya src/ içinde)
   if len(parts) < 2:
       ...

   # Doğru
   MINIMUM_PACKAGE_SEGMENTS = 2
   if len(parts) < MINIMUM_PACKAGE_SEGMENTS:
       ...

   # tests/ içinde bu serbesttir, sabite gerek yok
   assert len(result.stdout) < 200
   ```

8. **Bir fonksiyon 8'den fazla dallanma (`if`/`elif`/`for`/`except`, Ruff
   `PLR0912`) veya 6'dan fazla `return` ifadesi (Ruff `PLR0911`) asla
   içermez.**
   Yazmadan önce mantığı adı anlamlı, tek sorumluluklu alt fonksiyonlara böl
   (örn. `resolve_configured_path`, `string_keyed_mapping`). Erken `return`
   ile early-exit yazarken bile fonksiyon başına 6 dönüş noktasını aşıyorsan,
   doğrulama adımlarını ayrı bir yardımcı fonksiyona taşı. Sonradan refactor
   etme — baştan böl.

9. **Import sıralaması her zaman stdlib → third-party → local ve alfabetik
   olur; kullanılmayan import asla bırakılmaz.**
   `ruff format`/`ruff check --fix` çalıştırmadan önce elle kontrol et.

10. **Bağımsız gereksinimler asla tek bir testte birleştirilmez.**
    Bir test fonksiyonu **yazmadan önce**, prompt'taki gereksinim listesinden
    kaç ayrı maddeyi kapsadığını say. İkiden fazla bağımsız senaryoyu
    (örn. "boş dizin yok sayılır", "gizli dizin yok sayılır", "yalnız
    `__pycache__` içeren dizin yok sayılır") tek fonksiyonda birleştirme —
    her senaryo için ayrı, adı senaryoyu birebir yansıtan bir test fonksiyonu
    yaz. Testleri sonradan bölmek yerine baştan ayrı yaz.
    ```python
    # Yanlış — tek testte üç bağımsız senaryo
    def test_ignores_empty_hidden_and_cache_only_directories(tmp_path): ...

    # Doğru — her senaryo kendi testinde
    def test_ignores_empty_directory(tmp_path): ...
    def test_ignores_hidden_directory(tmp_path): ...
    def test_ignores_cache_only_directory(tmp_path): ...
    ```

11. **Bir fonksiyona asla pozisyonel `bool` parametre geçirilmez (Ruff
    `FBT001`/`FBT002`/`FBT003`).**
    Çağıran tarafta `run(True)` gibi bir çağrı neyin açılıp kapandığını
    okuyarak anlaşılmaz. Her `bool` parametreyi `*` ile keyword-only yap.
    ```python
    # Yanlış
    def run(project_root: Path, write: bool) -> int: ...
    run(project_root, True)

    # Doğru
    def run(project_root: Path, *, write: bool) -> int: ...
    run(project_root, write=True)
    ```

12. **`raise Exception(...)` veya `raise ValueError(...)` gibi yerleşik,
    proje-özel olmayan bir exception türü asla doğrudan fırlatılmaz (Ruff
    `TRY002`).**
    Her modülün kendi `ConfigurationError` benzeri özel exception sınıfı
    olur; hata her zaman o sınıftan fırlatılır.
    ```python
    # Yanlış
    raise ValueError("Invalid YAML mapping.")

    # Doğru
    class ConfigurationError(Exception):
        """Raised when the project structure configuration is unusable."""

    message = "Invalid YAML mapping."
    raise ConfigurationError(message)
    ```

13. **`except Exception:` veya çıplak `except:` asla kullanılmaz (Ruff
    `BLE`).**
    Her zaman yakalanacak hatanın somut türünü (`OSError`, `yaml.YAMLError`,
    `SyntaxError` gibi) belirt; birden fazla türü `except (A, B):` ile grupla.
    ```python
    # Yanlış
    try:
        ...
    except Exception as error:
        ...

    # Doğru
    try:
        ...
    except (OSError, yaml.YAMLError) as error:
        ...
    ```

## Genel kurallar

- Proje adı, paket adı veya yolları asla hardcode etme; her zaman
  yapılandırma dosyasından oku.
- Yeni bir doğrulama hatası bulduğunda kapsamı genişletme — yalnız o hatayı
  düzelt, ilgisiz alanlara dokunma.
- Test ve implementasyon dosyası dışında istenmeyen dosyayı değiştirme veya
  silme.

## Doğrulama Sırası

1. **Kod yazdıktan hemen sonra, `poe check`'i beklemeden otomatik
   düzeltilebilir adımları doğrudan çalıştır:**
   ```bash
   uv run --locked ruff check --fix <değiştirilen dosyalar>
   uv run --locked ruff format <değiştirilen dosyalar>
   ```
   `ruff check` önce çalıştırıp sonra `--fix` ile tekrar çalıştırma —
   bu gereksiz bir tur. Lint ve format otomatik düzeltilebilir, o yüzden
   önce düzelt.

2. **Dar kapsamlı, hedefli testi çalıştır:**
   ```bash
   uv run --locked poe test-target <path_or_node_id>
   ```
   Typecheck ve test hataları otomatik düzeltilemez — bunlar gerçek
   "çalıştır, gör, düzelt" döngüsünü gerektirir, atlanamaz.

3. **Değişiklik integration sınırını etkiliyorsa ek olarak:**
   ```bash
   uv run --locked poe test-integration
   ```

4. **Dar test geçtikten sonra final kapıyı çalıştır:**
   ```bash
   uv run --locked poe check
   ```
   Bu noktada lint/format zaten adım 1'de düzeltildiği için `lint-check`/
   `format-check` neredeyse her zaman ilk seferde geçer; `poe check`
   yalnızca typecheck, test ve yapı indeksini gerçekten doğrular. `poe
   check` dosya değiştirmez — bu kasıtlı, final kapı olarak kalmalı.

## Proje Yapısı İndeksi

`project_structure.yaml`, hangi domain'in nerede olduğunu, hangi test
dosyalarının ona ait olduğunu ve domain'ler arası bağımlılıkları
makine-okunur biçimde tutar. Amacı, her görevde depoyu baştan taramak
yerine bu tek dosyaya bakmaktır.

1. **Bir domain'in konumu, testleri veya bağımlılıkları sorulduğunda —
   önce `project_structure.yaml`'ı oku.**
   İndeks soruyu cevaplıyorsa, aynı bilgi için ayrıca `find`, geniş `rg
   --files` veya `ls -R` çalıştırma. İndeksi okuduktan sonra hâlâ geniş bir
   tarama yapıyorsan, bu indeksin eksik/güncel olmadığından şüphelendiğin
   anlamına gelir — o zaman önce adım 3'teki `check-project-structure`'ı
   çalıştırıp indeksin güncelliğini doğrula, doğrudan tarama yapma.
   ```bash
   # Yanlış — index zaten var, yine de tam tarama yapıyorsun
   sed -n '1,240p' project_structure.yaml
   find . -maxdepth 4 -type f -print

   # Doğru — index yeterliyse orada dur
   sed -n '1,240p' project_structure.yaml
   # (soru indeksten cevaplanabiliyorsa devam et, tarama yapma)
   ```

2. **İndeks yalnız şu sorulara cevap verir: bir domain nerede, hangi test
   dosyaları ona ait, hangi domain'lere bağımlı.** Kod içeriğini, fonksiyon
   imzalarını veya iş mantığını göstermez — bunlar için ilgili kaynak
   dosyasını `view`/`Read` etmen gerekir, indeks bunun yerine geçmez.

3. **Bir domain veya indekslenen test dosyası eklendiğinde, kaldırıldığında,
   taşındığında ya da domain bağımlılığı değiştiğinde, görevi bitirmeden
   önce indeksi güncelle:**
   ```bash
   uv run --locked poe sync-project-structure
   ```
   Bunu Doğrulama Sırası'ndaki adım 4'ten (`poe check`) önce çalıştır —
   `poe check` zaten `check-project-structure` içerir ve indeks güncel
   değilse başarısız olur. Dosya yapısını değiştiren bir görevi indeksi
   güncellemeden "tamamlandı" olarak bildirme.

4. **İndeksin kendisi asla elle düzenlenmez.** `domains` alanı yalnız
   `sync_project_structure.py` tarafından üretilir; `version`, `package`,
   `paths` alanlarını elle değiştirebilirsin ama `domains` alanına asla
   elle satır ekleme/çıkarma — sonraki `sync` çalıştırmasında farkı
   gizler ve indeksin gerçek kaynak kodla senkronizasyonunu bozar.
