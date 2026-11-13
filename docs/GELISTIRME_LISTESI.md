# `polyctl` — Önceliklendirilmiş Geliştirme Listesi (Backlog & Yol Haritası)

> **Tarih:** 13 Kasım 2026  
> **Kaynaklar:** `docs/RAKIP_ANALIZI.md` (Özellik Matrisi boşlukları) ve `docs/GELIR_MODELI.md` (Ticarileşme gereksinimleri)  
> **Önceliklendirme Formülü:** `Skor = (Gelir Etkisi [1-5] × Kullanıcı Değeri [1-5]) ÷ Efor [1-5]`  
> *(P0: Skor ≥ 6.0 | P1: Skor 3.5 – 5.9 | P2: Skor < 3.5)*

---

## 1. Rakip Analizi Matrisindeki Tüm `yok` ve `kısmi` Kalemlerin Eşlemesi

`docs/RAKIP_ANALIZI.md` Bölüm 3'teki özellik matrisinde `polyctl` için `yok` veya `kısmi` olarak tespit edilen **10 yetenek boşluğunun tamamı** eksiksiz olarak aşağıdaki iş kalemlerine dönüştürülmüştür:

| Matris # | Matristeki Yetenek Adı | Mevcut Durum | İş Kalemi ID | Öncelik | Gelir (1-5) | Değer (1-5) | Efor (1-5) | Skor | Durum |
| :-: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#16** | Ticari Lisanslama, Abonelik/Ödeme (`iyzico` + Sağlayıcı Soyutlaması) ve Faturalama | `yok` | **P0-1** | **P0** | 5 | 5 | 2 | **12.5** | `[x] Tamamlandı` |
| **#13** | Ajan Token, Çağrı ve Maliyet Muhasebesi (Kullanım Ölçümü / Metering) | `kısmi` | **P0-2** | **P0** | 5 | 5 | 2 | **12.5** | `[x] Tamamlandı` |
| **#14** | Maliyet Bütçe Limitleri (Spend Caps), Kota Kesici ve Uyarılar | `yok` | **P0-2** | **P0** | 5 | 5 | 2 | **12.5** | `[x] Tamamlandı` |
| **#7** | Pre-Commit Gizli Anahtar (Secret), PII ve Güvenlik Politikası Tarayıcısı | `yok` | **P0-3** | **P0** | 4 | 5 | 2 | **10.0** | `[x] Tamamlandı` |
| **#15** | Yerel/Web Görsel Yönetişim, Filo ve FinOps Panosu (Web UI Dashboard) | `yok` | **P0-4** | **P0** | 5 | 5 | 3 | **8.3** | `[x] Tamamlandı` |
| **#10** | Kurumsal Uyumluluk Dışa Aktarımı (SOC 2 / ISO 42001 / KVKK İmzalı Kanıt Paketi) | `yok` | **P1-1** | **P1** | 5 | 4 | 4 | **5.0** | `[ ] Bekliyor` |
| **#11** | Ekip Rol Tabanlı Yetkilendirme (RBAC) ve Politika-Kod (`policy-as-code`) Motoru | `kısmi` | **P1-2** | **P1** | 4 | 4 | 3 | **5.3** | `[ ] Bekliyor` |
| **#8** | PR / CI-CD Otomatik İnceleme Entegrasyonu (GitHub Actions / GitLab CI / SARIF) | `kısmi` | **P1-3** | **P1** | 4 | 4 | 3 | **5.3** | `[ ] Bekliyor` |
| **#17** | Dış Bildirim ve İş Akışı Kancaları (Slack / Discord / Webhook / Jira) | `yok` | **P2-1** | **P2** | 3 | 3 | 3 | **3.0** | `[ ] Bekliyor` |
| **#12** | Çoklu Depo / Organizasyonel Filo Senkronizasyonu ve Merkezi Denetim | `yok` | **P2-2** | **P2** | 4 | 3 | 4 | **3.0** | `[ ] Bekliyor` |

---

## 2. P0 İş Kalemleri (Uygulanan Kritik Gelir ve Güvenlik Kaldıraçları)

### [x] P0-1: Sağlayıcı Soyutlamalı Ödeme (`iyzico` + Local), Paket/Abonelik Yönetimi ve Faturalama (`billing`)
- **Matris Kalemi:** `#16` (`yok` → `var`) · **Skor:** `12.5` · **Efor:** S–M (2) · **Bağımlılık:** Yok.
- **Kapsam:** `src/polyctl/billing.py` içinde `PaymentProvider` soyutlaması:
  - `IyzicoPaymentProvider`: `iyzico` Checkout Form API'si (`/payment/iyzipos/checkoutform/initialize/auth/ecom` ve `/payment/iyzipos/checkoutform/auth/ecom/detail`) `IYZWSv2` HMAC-SHA256 imza üretimi; `IYZICO_API_KEY` ve `IYZICO_SECRET_KEY` ortam değişkenlerini okur, eksik kimlikte veya doğrulanmamış ödemede (`PENDING_CHECKOUT`) kapalı-güvenli (`ok: False`) davranır; `--payment-token` ile tekil token tekrarını (`REPLAYED`), sepet/plan bağını (`basketId`), `paymentStatus == "SUCCESS"` ve `paidPrice` tutarını doğrular.
  - `LocalMockPaymentProvider`: Çevrimdışı test/simülasyon sağlayıcısı (`--provider local`, `status: "SIMULATED"`, `SIM-YYYYMMDD-XXXX.json`).
  - Paket kataloğu (`community`, `pro`, `team`, `enterprise`), VKN/TCKN maskelemesi (`tax_id_masked`) ve SHA-256 sağlama toplamı (`checksum_matches`) veya `POLYCTL_BILLING_SIGNING_KEY` ile HMAC-SHA256 (`integrity_verified`) doğrulamalı fatura kaydı.
- **Kabul Kriterleri:**
  1. `polyctl billing plans --currency TRY` 4 paketi, TRY/USD fiyatlarını ve kotaları listeler.
  2. `polyctl billing subscribe --plan pro --seats 1 --currency TRY --provider iyzico` ödeme formunu başlatır (`PENDING_CHECKOUT`); `--payment-token` ile ödeme doğrulandığında (veya simülasyon için `--provider local`) abonelik ve fatura kaydını oluşturur.
  3. `polyctl billing status --json` ve `polyctl billing invoices --json` aktif aboneliği ve fatura doğrulama durumunu döndürür.

### [x] P0-2: Ajan Kullanım Ölçümü (Usage Metering), Maliyet Muhasebesi ve FinOps Bütçe Kesici (Spend Caps)
- **Matris Kalemleri:** `#13` (`kısmi` → `var`) ve `#14` (`yok` → `var`) · **Skor:** `12.5` · **Efor:** S–M (2) · **Bağımlılık:** `P0-1`.
- **Kapsam:** Aktif fatura dönemi (`YYYY-MM`) bazında hash-zincirli ve imzalı kullanım ölçümü (`record_usage`), faturalanmamış aşım (`unbilled_overage_units`) takibi, `check_budget_gate` bütçe/kota kesicisi ve `maybe_meter_cmd` ile üst-seviye `review`, `verify`, `security-scan` komutlarının otomatik ölçümü.
- **Kabul Kriterleri:**
  1. `polyctl billing meter review --model claude-sonnet-4-5 --prompt-tokens 4000 --completion-tokens 1000` ile kullanım olayı `.polyctl/billing/usage.jsonl` dosyasına hash-zincirli ve `integrity_sha256` imzalı olarak kaydedilir.
  2. Varsayılan `--soft-cap` modunda aşım uyarı üretir (`BILLING WARNING`); `polyctl billing budget --cap-try 5000 --cap-usd 150 --hard-cap` ile katı tavan etkinleştirildiğinde ise `polyctl billing budget --check` ve kapıdaki komutlar aşım durumunda çıkış kodu `1` döndürür.
  3. Paket yenileme/yükseltmede yalnızca henüz faturalanmamış aşım (`unbilled_overage_units`) önceki paketin birim fiyatından faturaya yansıtılır.

### [x] P0-3: Pre-Commit Gizli Anahtar (Secret), PII ve Güvenlik Politikası Tarayıcısı (`security-scan`)
- **Matris Kalemi:** `#7` (`yok` → `var`) · **Skor:** `10.0` · **Efor:** S–M (2) · **Bağımlılık:** Yok.
- **Kapsam:** `src/polyctl/security.py` ve `polyctl security-scan` komutu (`SEC-001`..`SEC-008`: Anthropic, OpenAI, AWS, GitHub PAT, PEM özel anahtar, Slack/canlı ödeme anahtarı, URL içi parola ve TCKN PII). `lib.git_binary()` ile `git diff --cached --no-ext-diff --no-textconv` üzerinden staged değişiklikleri veya `--paths` ile verilen yolları tarar; PII ve gizli dizgileri son karakterlerini göstermeden maskeler (`REDACTED`).
- **Kabul Kriterleri:**
  1. `polyctl security-scan` staged diff veya `--paths` dosyalarını tarar; temizse `0`, bulgu veya git/dosya hatası varsa kapalı-güvenli `1` koduyla çıkar.
  2. Çıktıda hiçbir gizli anahtar veya TCKN açık metin olarak yer almaz.

### [x] P0-4: Görsel Web Yönetişim, Filo ve AI FinOps Panosu (`polyctl watch --web` `/billing` Yüzeyi)
- **Matris Kalemi:** `#15` (`yok` → `var`) · **Skor:** `8.3` · **Efor:** M (3) · **Bağımlılık:** `P0-1`, `P0-2`, `P0-3`.
- **Kapsam:** `src/polyctl/web.py` ve `src/polyctl/parts/cli_status.py` içinde `/billing` HTML görünümü ve `/api/billing` JSON uç noktası (aktif paket, kota ilerleme çubuğu, bütçe durumu, son güvenlik taraması ve fatura tablosu; sıkı CSP ve sıfır harici JS).
- **Kabul Kriterleri:**
  1. `GET /billing` semantic HTML kartlarıyla abonelik, kota, bütçe, güvenlik ve fatura tablosunu sunar.
  2. `GET /api/billing` `schema_version: 1` ile abonelik, kullanım, güvenlik ve fatura verilerini JSON olarak döndürür.

---

## 3. P1 ve P2 İş Kalemleri (Sonraki Fazlar)

- **[ ] P1-1 (`#10`, Skor `5.0`, Efor `4`):** Kurumsal Uyumluluk ve Denetim Kanıt Paketi Dışa Aktarımı (SOC 2 / ISO 42001 / KVKK imzalı manifest).
- **[ ] P1-2 (`#11`, Skor `5.3`, Efor `3`):** Ekip Rol Tabanlı Yetkilendirme (RBAC) ve Politika-Kod (`policy-as-code`) Motoru.
- **[ ] P1-3 (`#8`, Skor `5.3`, Efor `3`):** CI/CD Otomatik İnceleme ve SARIF 2.1.0 / JUnit Raporlama Entegrasyonu.
- **[ ] P2-1 (`#17`, Skor `3.0`, Efor `3`):** Dış Bildirim ve İş Akışı Kancaları (Slack / Discord / Genel Webhook).
- **[ ] P2-2 (`#12`, Skor `3.0`, Efor `4`):** Çoklu Depo / Organizasyonel Filo FinOps ve Kalite Toplayıcısı.
