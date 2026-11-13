# `polyctl` — Rakip Analizi ve Pazar Konumlandırması (Kasım 2026)

> **Tarih:** 13 Kasım 2026  
> **Kapsam:** Çok-ajanlı geliştirme orkestrasyonu, bağımsız ajan kod incelemesi (pre-commit / PR), kurcalamaya dayanıklı (tamper-evident) yönetişim defteri ve AI FinOps / gözlemlenebilirlik alanında küresel ve Türkiye pazarındaki en güçlü 8 rakibin incelenmesi.

---

## 1. Yönetici Özeti ve `polyctl`'in Benzersiz Konumu

2025–2026 itibarıyla yazılım mühendisliği ekipleri, tek bir AI kodlama asistanı kullanmaktan **çoklu ajan filolarını** (`Claude Code`, `Codex`, `Gemini CLI`, `Kiro`, `Cursor`, `Aider`, `OpenHands`) paralel `git worktree` ve konteynerlerde çalıştırmaya geçmiştir. Mevcut araç ekosistemi üç ayrı siloya bölünmüştür:

1. **Çoklu Ajan ve Worktree Orkestratörleri** (*Claude Squad*, *OpenHands*, *Aider*): Ajanları paralel çalıştırır ancak **bağımsız çapraz-model (cross-family) kod inceleme kapısı**, **kriptografik hash-zincirli denetim defteri (ledger)** ve **pre-commit indeks kilidi** sunmaz.
2. **AI PR İnceleme ve DevSecOps ASPM Araçları** (*CodeRabbit*, *Cursor Bugbot*, *Invicti ASPM / Kondukto*): Kod commit edilip PR açıldıktan sonra (post-commit / CI aşamasında) devreye girer. Yerel ajanların pre-commit aşamasında kendi hatalı kodlarını veya gizli anahtarlarını (`secrets`) repoya sokmasını kaynağında durduramaz.
3. **LLM Ağ Geçidi ve Gözlemlenebilirlik Platformları** (*Portkey*, *LangSmith*): HTTP API çağrılarını ve token maliyetlerini izler, ancak yerel CLI ajan süreçlerini (`tmux`/ACP), `git worktree` izolasyonunu ve commit/merge yetki sınırlarını yönetemez.

**`polyctl`'in Kesişim Noktası:**  
`polyctl`, **sıfır dış bağımlılıklı (Python stdlib)** yerel/hibrit çekirdeğiyle çoklu ajan orkestrasyonunu (`claude`, `codex`, `gemini`, `kiro`, `acp`), **pre-commit aşamasında çapraz-model bağımsız denetimi** (UHP `2026-10-19` uyumu) ve **SHA-256 hash-zincirli kurcalamaya dayanıklı yönetişim defterini (`ledger`)** tek bir araçta birleştiren ilk **Çok-Ajanlı Mühendislik Yönetişimi ve Orkestrasyon** platformudur.

---

## 2. İncelenen 8 Rakip Profili (Küresel + Türkiye)

### 2.1. Claude Squad (`smtg-ai/claude-squad`) — *Küresel / Açık Kaynak*
- **Kategori:** Yerel Terminal (TUI) Çoklu Ajan & Git Worktree Multiplexer.
- **Mimari & Özellikler:** Go ile yazılmış, `tmux` ve `git worktree` üzerinde birden fazla yerel CLI ajanını (`Claude Code`, `Codex`, `Gemini CLI`, `Aider`) izole çalışma alanlarında paralel koşturan terminal arayüzü.
- **Fiyatlandırma:** Ücretsiz / Açık Kaynak (AGPL-3.0) + BYOK.
- **Kullanıcı Övgüleri:** Hafif, hızlı kurulum, tek ekranda paralel ajanları izleme kolaylığı, `git worktree` çakışmalarını önlemesi.
- **Kullanıcı Şikayetleri:** Ajanların ürettiği kodu başka bir model ailesine denetleten bağımsız bir kalite/güvenlik kapısı yok; ekip düzeyinde RBAC, denetim izi, bütçe sınırı ve web panosu bulunmuyor.
- **Kaynak:** [GitHub — smtg-ai/claude-squad](https://github.com/smtg-ai/claude-squad)

### 2.2. Cursor Cloud Agents & Bugbot — *Küresel / Ticari*
- **Kategori:** Bulut Tabanlı Otonom Ajanlar + AI PR İnceleme (`Bugbot`).
- **Mimari & Özellikler:** Uzak Linux sanal makinelerinde paralel ajan çalıştırma, Slack/Web/Linear üzerinden ajan tetikleme, PR açıldığında çalışan `Bugbot` kod inceleme ve güvenlik denetimi, SAML/SSO, SCIM ve yönetici harcama limitleri.
- **Fiyatlandırma (2025–2026):** Free ($0), Plus ($8/ay), Premium ($30/ay), Super ($100/ay), Ultra ($200/ay), Teams ($30–$200/koltuk/ay) + `Bugbot` (~$1.00–$1.50/inceleme veya $40/kullanıcı/ay eklenti).
- **Kullanıcı Övgüleri:** IDE ve PR akışıyla pürüzsüz entegrasyon, `Bugbot`'un PR üzerindeki bağlamsal hata yakalama başarısı.
- **Kullanıcı Şikayetleri:** Kredi tüketim hızının öngörülemezliği, bulut VM zorunluluğu (veri egemenliği endişesi), rakip yerel CLI harness'larını (`Claude Code`, `Kiro`, `Gemini CLI`) orkestre edememesi.
- **Kaynaklar:** [Cursor Pricing](https://cursor.com/pricing) · [Cursor Bugbot Docs](https://docs.cursor.com/bugbot)

### 2.3. CodeRabbit — *Küresel / Ticari*
- **Kategori:** Otonom AI PR & CLI Kod İnceleme ve Yönetişim Platformu.
- **Mimari & Özellikler:** GitHub/GitLab/Azure DevOps PR'ları ve yerel CLI üzerinde satır bazlı AI kod incelemesi, "AI Slop" tespiti, etki alanı (Blast Radius) analizi, 40+ SAST/linter entegrasyonu (`Semgrep`, `Gitleaks`, `Checkov`), Jira/Linear doğrulaması ve SOC 2 Type II uyumu.
- **Fiyatlandırma (2025–2026):** Free ($0), Essentials ($30/geliştirici/ay), Team ($60/geliştirici/ay), Advanced ($90/geliştirici/ay), Enterprise (Özel, ~$15.000+/ay).
- **Kullanıcı Övgüleri:** Hızlı PR özeti, 40+ statik analiz aracını LLM bağlamıyla birleştirmesi.
- **Kullanıcı Şikayetleri:** Çok fazla gürültülü (nitpick) yorum üretmesi, çoklu ajan orkestrasyonu yapmaması, pre-commit git indeks kilidi olmaması ve yüksek koltuk maliyeti ($60–$90/ay).
- **Kaynaklar:** [CodeRabbit Pricing](https://www.coderabbit.ai/pricing) · [CodeRabbit Docs](https://docs.coderabbit.ai/)

### 2.4. OpenHands (AllHands AI) — *Küresel / Açık Kaynak + Kurumsal Bulut*
- **Kategori:** Otonom Yazılım Mühendisliği Ajanları Platformu (SDK + CLI + Web GUI + Enterprise Cloud).
- **Mimari & Özellikler:** Docker/Kubernetes kum havuzlarında çalışan otonom ajanlar, Web UI üzerinden canlı ajan izleme, Slack/Jira/GitHub entegrasyonu, çoklu LLM desteği ve kurumsal RBAC.
- **Fiyatlandırma:** Open Source (MIT, ücretsiz BYOK) · OpenHands Cloud / Enterprise (kullanım bazlı kredi + VPC/Self-Hosted lisans).
- **Kullanıcı Övgüleri:** Güçlü SWE-bench başarımı, tam izole konteyner güvenliği, açık kaynak esnekliği.
- **Kullanıcı Şikayetleri:** Ağır Docker/Kubernetes altyapı gereksinimi, dış yerel CLI ajanlarını (`Claude Code`, `Codex`, `Kiro`) doğrudan yönetmek yerine kendi iç ajan döngüsünü dayatması.
- **Kaynaklar:** [OpenHands Official Site](https://www.all-hands.dev/) · [GitHub — All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands)

### 2.5. Aider — *Küresel / Açık Kaynak*
- **Kategori:** Git-Yerli (Git-Native) Terminal AI Eşli Programlama Aracı.
- **Mimari & Özellikler:** Depo haritası (repository map) çıkarma, Mimari/Editör çift model modu, otomatik git commit oluşturma, lint/test koşumu.
- **Fiyatlandırma:** Ücretsiz / Açık Kaynak (Apache-2.0) + BYOK.
- **Kullanıcı Övgüleri:** Git ile derin uyum, büyük kod tabanlarında yüksek bağlam doğruluğu, hızlı yerel çalışma.
- **Kullanıcı Şikayetleri:** Tek oturum/tek ajan odaklı olması (çoklu ajan filo yönetimi, görev kuyruğu veya ajanlar arası mesajlaşma yok), bağımsız denetçi kapısı sunmaması.
- **Kaynaklar:** [Aider Official Site](https://aider.chat/) · [GitHub — Aider-AI/aider](https://github.com/Aider-AI/aider)

### 2.6. Portkey (Prisma AIRS AI Gateway) — *Küresel / Ticari + Açık Kaynak Ağ Geçidi*
- **Kategori:** AI Gateway, Guardrails, Gözlemlenebilirlik ve AI FinOps Kontrol Düzlemi.
- **Mimari & Özellikler:** 1.600+ LLM yönlendirme, otomatik yedekleme (fallback), kullanıcı/ekip bazlı bütçe ve hız limitleri (spend caps & rate limits), MCP yönetişimi, PII/Secret maskeleme guardrails, SOC 2 / ISO 27001 denetim günlükleri.
- **Fiyatlandırma (2025–2026):** Open Source Gateway ($0), Developer ($0/ay, 10k log), Production ($49/ay taban, 100k log + $9/100k log), Enterprise (Özel).
- **Kullanıcı Övgüleri:** Çoklu LLM maliyet kontrolü, gerçek zamanlı bütçe kesiciler (circuit breakers), uyumluluk raporları.
- **Kullanıcı Şikayetleri:** Yalnızca HTTP API katmanında çalışır; yerel `git worktree` yaşam döngüsünü, dosya kapsam kilitlerini (`scope locks`) ve git commit/merge yetkilerini bilmez.
- **Kaynaklar:** [Portkey Pricing](https://portkey.ai/pricing) · [GitHub — Portkey-AI/gateway](https://github.com/Portkey-AI/gateway)

### 2.7. LangSmith (LangChain) — *Küresel / Ticari*
- **Kategori:** Ajan İzleme (Tracing), Değerlendirme (Evals) ve Gözlemlenebilirlik Platformu.
- **Mimari & Özellikler:** Çok adımlı ajan çağrı ağaçlarını (trace trees) görselleştirme, gecikme/token/maliyet kırılımı, regresyon değerlendirmeleri (evals).
- **Fiyatlandırma (2025–2026):** Developer ($0/ay, 5k trace), Plus ($39/kullanıcı/ay, 10k trace + $0.50/1k base trace), Enterprise ($100.000+/yıl).
- **Kullanıcı Övgüleri:** Karmaşık ajan hatalarını ayıklamada sınıfının en iyisi trace görselleştirmesi.
- **Kullanıcı Şikayetleri:** Kod içine SDK gömülmesini gerektirir; dış kodlama ajanlarını orkestre edemez ve git commit kapısı olarak çalışmaz.
- **Kaynak:** [LangChain / LangSmith Pricing](https://www.langchain.com/pricing)

### 2.8. Invicti ASPM (eski adıyla Kondukto) — *Türkiye Çıkışlı Küresel Rakip / Ticari*
- **Kategori:** Uygulama Güvenliği Duruş Yönetimi (ASPM) ve DevSecOps Orkestrasyonu.
- **Mimari & Özellikler:** Türkiye'den çıkıp küreselleşen ve Invicti tarafından satın alınarak **Invicti ASPM** adını alan platform. SAST, DAST, SCA, IaC ve konteyner tarayıcılarını tek merkezde toplar; CI/CD boru hatlarına otomatik güvenlik kapıları koyar; SBOM/VEX üretir; RBAC ve On-Premise kurulum sunar. Türkiye'de finans, bankacılık ve savunma pazarında (BDDK, KVKK, DORA, ISO 42001) güçlü referanslara sahiptir.
- **Fiyatlandırma:** Kurumsal Özel Teklif (Geliştirici koltuğu veya uygulama ölçeğine göre yıllık lisans; bulut veya on-premise).
- **Kullanıcı Övgüleri:** Türkiye ve EMEA kurumsal regülasyonlarına (On-Premise, RBAC, denetim izi) tam uyum, güvenlik tarayıcılarını CI/CD içinde orkestre edebilmesi.
- **Kullanıcı Şikayetleri:** Geleneksel AppSec/CI-CD odaklıdır; yerel geliştirici makinesindeki çoklu AI kodlama ajanlarını orkestre etmez, çapraz-model kod incelemesi veya ajan token/maliyet muhasebesi yapmaz.
- **Kaynaklar:** [Kondukto / Invicti ASPM Official](https://kondukto.io/) · [Invicti Official](https://www.invicti.com/)

---

## 3. Özellik Karşılaştırma Matrisi (`var` / `kısmi` / `yok`)

Aşağıdaki matriste her yetenek `var`, `kısmi` veya `yok` olarak işaretlenmiştir. **`polyctl` sütunundaki tüm `yok` ve `kısmi` kalemler doğrudan geliştirme listesindeki iş kalemlerine dönüştürülmüştür.**

| # | Yetenek / Özellik | `polyctl` (Mevcut) | Claude Squad | Cursor (Cloud + Bugbot) | CodeRabbit | OpenHands | Aider | Portkey | LangSmith | Invicti ASPM (Kondukto) |
| :- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A** | **Çoklu Ajan & Worktree Orkestrasyonu** | | | | | | | | | |
| 1 | Çoklu CLI/ACP Ajan Orkestrasyonu (`claude`, `codex`, `gemini`, `kiro`) | `var` | `var` | `kısmi` | `yok` | `kısmi` | `yok` | `yok` | `yok` | `yok` |
| 2 | Git Worktree İzolasyonu ve Dosya Kapsam Kilidi (`scope lock`) | `var` | `kısmi` | `kısmi` | `yok` | `kısmi` | `yok` | `yok` | `yok` | `yok` |
| 3 | Ajanlar Arası Asenkron Posta Kutusu (`mail`) ve Görev Panosu (`board`) | `var` | `yok` | `kısmi` | `yok` | `kısmi` | `yok` | `yok` | `yok` | `yok` |
| **B** | **Kod İnceleme, Kalite Kapıları ve Güvenlik** | | | | | | | | | |
| 4 | Çapraz-Model (Cross-Family) Zorunlu Pre-Commit İnceleme Kapısı | `var` | `yok` | `yok` | `kısmi` | `yok` | `kısmi` | `yok` | `yok` | `yok` |
| 5 | Pre-Commit Git İndeks Kilidi (`commit-check` + diff/verify/review hash) | `var` | `yok` | `yok` | `yok` | `yok` | `yok` | `yok` | `yok` | `yok` |
| 6 | UHP (`2026-10-19`) ve Çoklu Sağlayıcı API İnceleme Yönlendiricisi | `var` | `yok` | `yok` | `yok` | `yok` | `yok` | `kısmi` | `yok` | `yok` |
| 7 | Pre-Commit Gizli Anahtar (Secret), PII ve Güvenlik Politikası Tarayıcısı | `yok` | `yok` | `kısmi` | `var` | `kısmi` | `yok` | `var` | `yok` | `var` |
| 8 | PR / CI-CD Otomatik İnceleme Entegrasyonu (GitHub Actions / GitLab CI / SARIF) | `kısmi` | `yok` | `var` | `var` | `var` | `yok` | `yok` | `yok` | `var` |
| **C** | **Yönetişim, Denetim ve Uyumluluk (Governance & Compliance)** | | | | | | | | | |
| 9 | Kurcalamaya Dayanıklı (SHA-256 Hash-Chained) Yerel Denetim Defteri (`ledger`) | `var` | `yok` | `yok` | `yok` | `yok` | `yok` | `kısmi` | `yok` | `kısmi` |
| 10 | Kurumsal Uyumluluk Dışa Aktarımı (SOC 2 / ISO 42001 / KVKK İmzalı Kanıt Paketi) | `yok` | `yok` | `kısmi` | `var` | `kısmi` | `yok` | `var` | `var` | `var` |
| 11 | Ekip Rol Tabanlı Yetkilendirme (RBAC) ve Politika-Kod (`policy-as-code`) Motoru | `kısmi` | `yok` | `var` | `var` | `var` | `yok` | `var` | `var` | `var` |
| 12 | Çoklu Depo / Organizasyonel Filo Senkronizasyonu ve Merkezi Denetim | `yok` | `yok` | `var` | `var` | `var` | `yok` | `var` | `var` | `var` |
| **D** | **Gözlemlenebilirlik, AI FinOps ve Ticari Altyapı** | | | | | | | | | |
| 13 | Ajan Token, Çağrı ve Maliyet Muhasebesi (Kullanım Ölçümü / Metering) | `kısmi` | `yok` | `var` | `var` | `var` | `kısmi` | `var` | `var` | `yok` |
| 14 | Maliyet Bütçe Limitleri (Spend Caps), Kota Kesici ve Uyarılar | `yok` | `yok` | `var` | `kısmi` | `var` | `yok` | `var` | `var` | `yok` |
| 15 | Yerel/Web Görsel Yönetişim, Filo ve FinOps Panosu (Web UI Dashboard) | `yok` | `kısmi` | `var` | `var` | `var` | `yok` | `var` | `var` | `var` |
| 16 | Ticari Lisanslama, Abonelik/Ödeme (`iyzico` + Sağlayıcı Soyutlaması) ve Faturalama | `yok` | `yok` | `var` | `var` | `var` | `yok` | `var` | `var` | `var` |
| 17 | Dış Bildirim ve İş Akışı Kancaları (Slack / Discord / Webhook / Jira) | `yok` | `yok` | `var` | `var` | `var` | `yok` | `var` | `var` | `var` |

---

## 4. `polyctl` İçin Stratejik Çıkarımlar (`yok` ve `kısmi` Boşluklarının Analizi)

Matristeki veriler ışığında `polyctl`'in çekirdek teknik üstünlüğü (**#1, #2, #3, #4, #5, #6, #9**) rakiplerde bulunmayan bir **pre-commit çoklu ajan yönetişim temeli** sağlamaktadır. Açık kaynak çekirdekten **ücretli ekip/yönetişim katmanına** geçiş için şu 10 boşluğun (`yok` / `kısmi`) kapatılması gerekmektedir:

1. **Ticari Altyapı & Ödeme (`#16` - `yok`):** Sağlayıcı soyutlamalı ödeme katmanı (`iyzico` + yerel simülasyon sağlayıcısı), abonelik/katman doğrulaması (`community`, `pro`, `team`, `enterprise`) ve fatura kayıt sistemi.
2. **Kullanım Ölçümü & FinOps Bütçe Kesiciler (`#13` `kısmi`, `#14` `yok`):** İnceleme ve ajan çağrılarında token/maliyet ölçümü (metering), aylık harcama tavanı (spend cap) ve kota aşımında durdurma/uyarı.
3. **Pre-Commit Güvenlik & Gizli Anahtar Kapısı (`#7` - `yok`):** Ajanların yanlışlıkla API anahtarı, özel anahtar, TCKN/PII veya tehlikeli kod kalıplarını commit etmesini deterministik olarak engelleyen yerleşik tarayıcı (`polyctl security-scan`).
4. **Görsel Web Yönetişim ve FinOps Panosu (`#15` - `yok`):** Mühendislik yöneticilerine (EM/CTO) ajan filosunu, inceleme onay oranlarını, güvenlik taramasını ve harcama/fatura durumunu gösteren Web UI (`polyctl watch --web` üzerinde `/billing` yüzeyi).
5. **Ekip RBAC ve Politika-Kod Motoru (`#11` - `kısmi`):** Hangi rolün hangi dalda/klasörde değişiklik yapabileceğini ve minimum inceleyici kademesini belirleyen merkezi politika motoru.
6. **Kurumsal Uyumluluk & Denetim Kanıt Paketi (`#10` - `yok`):** Denetim defteri ve inceleme kayıtlarını SOC 2, ISO/IEC 42001 ve KVKK/BDDK denetçileri için imzalı kanıt paketine dönüştüren dışa aktarım (`polyctl export otlp --attested` ve uyumluluk paketi).
7. **CI/CD & SARIF Entegrasyonu (`#8` - `kısmi`):** GitHub Actions / GitLab CI içinde `polyctl` inceleme ve güvenlik bulgularını standart SARIF / JUnit formatında raporlama.
8. **Dış Bildirim & Webhook Kancaları (`#17` - `yok`):** Kapı reddi (`NEEDS_CHANGES`), bütçe aşımı veya kritik bulgularda Slack/Webhook bildirimi.
9. **Çoklu Depo / Organizasyonel Filo Toplayıcısı (`#12` - `yok`):** Birden fazla repo/worktree üzerindeki `polyctl` metriklerini tek bir ekip görünümünde birleştirme.
