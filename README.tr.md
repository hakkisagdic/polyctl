[English](README.md) | **Türkçe**

# polyctl

**Yapay zekâ ajanlarının commit ettiği kod ya önce gözden geçirilir, ya bir kişi gözden
geçirmesini atlar ya da polyctl onu işaretler.** Varsayılan olarak başka bir model ailesi, ajanın stage
ettiği değişikliğin tam kendisini gözden geçirir; git hook'u gerisini `git commit` anında reddeder.
Bir defter her kararı kaydeder; polyctl atlanan bir değişikliği indikten sonra gözden geçirir, içeriğine
hiçbir gözden geçirmenin ya da atlamanın izin vermediği bir commit'i de `polyctl doctor` ve watchdog
işaretler. Bir kişi bir projede gözden geçirmeyi kayda geçerek kapatabilir, `polyctl features off review --by
<ad>`; o projenin commit'leri o zaman yalnızca doğrulamayla iner.

Zaten kullandığın kodlama ajanlarını bırakmazsın: Claude Code, Codex, Kiro, Qoder, OpenCode ve
aşağıdaki tablodaki diğerleri. `polyctl` onların üstünde durur. Bir ajanın stage ettiği değişikliğin
tam kendisinde gate'lerini koşturur, o değişikliği başka aileden bir modele gözden geçirtir ve
yalnızca o değişikliğin commit edilmesine izin verir. Gerisini hook `git commit` anında reddeder;
her karar, kurcalandığını belli eden bir deftere yazılır.

polyctl 0.7.0 macOS üzerinde geliştirilir ve desteklenir; Linux CI'da test paketini çalıştırır ancak henüz desteklenen bir platform değildir; Windows'ta 29 test başarısız olur (WINDOWS-LANE-0.7, docs/backlog.md) ve Windows sonraki bir sürümü bekler.

## Neden

- **Ajanlar kimsenin okuyabileceğinden hızlı commit eder.** Bir ağaçta geçen test, commit edilen
  ağaç hakkında hiçbir şey söylemez. `polyctl` commit yetkisini tek bir stage edilmiş ağaca verir; hook
  başka her ağacı reddeder.
- **Kendi ailesinin işini gözden geçiren model, o ailenin kör noktalarını paylaşır.** Gözden
  geçiren varsayılan olarak başka bir model ailesindendir ya da adını verdiğin bir kişidir, ve
  yalnızca okuyan araçlarla çalışır.
- **Araçlarını bırakmazsın.** `polyctl` her ajanın kendi oturum deposunu okur ve komut satırını sürer.
  Benimsemek, işini yeni bir şeyin içinde yeniden başlatmak demek değildir.

## İlk gözden geçirilmiş commit'e beş dakika

Önce görmek istersen `polyctl demo`, bir değişikliği geçici bir projede polyctl'den geçirir ([demo](docs/demo.md)).

```bash
pip install polyctl          # ya da: uv tool install polyctl
cd deponun-yolu
polyctl init --profile agy-codex          # agy (Gemini 4 Argon) yazar, Codex (gpt-6-luna) gözden geçirir; ya da codex-agy, claude-codex
git add .polyctl-project .gitignore && git commit -m "adopt polyctl"
polyctl hooks install                     # bundan sonra yalnızca yetki verilmiş aday commit edilir
```

Sonra, ajanının stage ettiği her değişiklik için:

```bash
polyctl status                            # ajanların ne yapıyor, ne seni bekliyor
polyctl verify                            # gate'lerin, stage edilmiş adayda
polyctl review                            # başka aileden bir model tam o adayı gözden geçirir
polyctl commit-ok                         # inebilir mi? kanıttan karar, reddin sebebiyle
polyctl commit -m "feat: ne değişti"      # commit et; trailer'larıyla o kanıta bağlı
```

[Başlarken](docs/getting-started.md) bunu adım adım anlatır; `polyctl prove` güvenceleri anlatmak
yerine atılacak bir adayda koşturur. [Profiller](docs/profiles.md) farklı ailelerden üç hazır
kurulum sunar — `agy-codex` (`antigravity` `verified: full`, Gemini 4 Argon uygulayıcı ve `codex`
`verified: partial`, `gpt-6-luna` gözden geçiren), `codex-agy` (`codex` `verified: partial`,
`gpt-6-astra` uygulayıcı ve `antigravity` `verified: full`, Gemini 4 Argon salt okunur gözden
geçiren ajanı) ve `claude-codex` (`claude-code` `verified: full` uygulayıcı ve `codex` `verified:
partial`, `gpt-6-luna` gözden geçiren); her birinde mimar `claude-code` (`verified: full`). Her rol
için tek harness kullanıyorsan (`--implementer claude-code`) `polyctl init` bir
[gözden geçirme katmanı](docs/roles.md#review-tiers) ister: aynı aileden başka bir model ("daha
zayıf bağımsızlık" etiketiyle) ya da bir kişi.

`polyctl status`, ana oturum yavaşlarken, durmuşken veya boştayken en son etkin olan ikincil
projeyi gösterir. `polyctl doctor`, `POLYCTL_GIT` ile seçilen bir betiği ve tanımadığı shell
hook'larını olası filtreler olarak bildirir; bkz. [gate'ler](docs/gates.md).

## Bir değişiklik nasıl iner

```text
ajan düzenler ve stage eder
  -> polyctl verify      gate'lerin, sonuçta hiçbir çıkarı olmayan bir şey tarafından yeniden koşturulur
  -> polyctl review      başka bir model ailesi o adayı ve etrafındaki kodu okur
  -> polyctl commit-ok   tam o ağaç için commit yetkisi, kanıttan verilir
  -> polyctl commit      commit, onu yetkiye bağlayan trailer'ları taşır
pre-commit hook'u başka her commit'i reddeder; push asla yetkilendirilmez
```

## Başka ne yapar

- **İzler.** `polyctl watch` canlı bir panel: her ajan ne yapıyor, bağlam ve maliyet, açık gözden
  geçirmeler, board, ve bir ajanın *meşgul ama hiçbir şey üretmiyor* olup olmadığı.
- **Yeniden başlatır.** Bir watchdog, iş ortasında duran bir turu fark eder ve dürter - asla bir
  sağlayıcı kesintisine, tur bütçesinin ötesine ya da bir kişinin devraldığı ağaca değil; bir ajanın
  oraya yazdığı hook'lar ya da talimatlar bir kişinin okumasını beklerken de değil (`polyctl harness seen`).
- **Durmaz.** Önceden yetkilendirilmiş işlerden oluşan bir board: seni bekleyen dilim sebebiyle
  park edilir, kuyruk boşalınca onu doldurması için mimar uyandırılır.
- **Telafi eder.** Atladığın bir gözden geçirme kaydedilir; `polyctl catchup` inen aralığı sonradan
  başka aileden bir gözden geçirene inceletir.
- **Güvenle gözden geçirir.** Gözden geçiren yalnızca okuyan araçlarla çalışır ve polyctl bunu her
  harness için ölçer: kiro-cli, soracak kişi yokken güvenilmeyen araçları yine de çalıştırdığı
  için Kiro gözden geçireni, polyctl'in onun için yazdığı salt okur bir ajan olarak koşar.

Her komut [docs/commands.tr.md](docs/commands.tr.md) içinde.

## Kurulum

`pip install polyctl`, `uv tool install polyctl` ya da
`brew install hakkisagdic/tap/polyctl`. Bilerek bağımlılık yok: polyctl, kontrol etmediği
makinelerde ajanları izler ve bağımlılık tam orada eksik olabilecek bir şeydir. Hiçbir şey
kurmadan, macOS'un ve çoğu Linux dağıtımının getirdiği Python ile bir klondan çalışır:

```bash
git clone https://github.com/hakkisagdic/polyctl ~/polyctl
mkdir -p ~/.local/bin && ln -s ~/polyctl/bin/polyctl ~/.local/bin/polyctl    # ~/.local/bin PATH'te olmalı
```

Kabuk alias'ı değil, symlink: polyctl'in commit hook'unu çalıştıran `/bin/sh` de, watchdog'un senin
kabuğun olmadan başlattığı ajan da alias'ı göremez. **Windows**'ta `bin/polyctl.ps1`, hiçbir şey
kurmadan `status`, `board` ve `doctor`'ı karşılar; gerisi için
`winget install Python.Python.3.12 && pip install polyctl` ([windows](docs/windows.md)).

polyctl'i yönettiği projelerin dışına kur, asla birinin içindeki bir `.venv`'e değil: oraya bir ajan
yazabilir ve Python, orada bıraktığı bir `.pth` dosyasını polyctl başlamadan çalıştırır. polyctl böyle bir
dosyanın adını verir, `polyctl doctor` da ağacın içindeki bir kurulumu söyler
([safety](docs/safety.md#what-python-runs-as-it-starts-from-inside-the-tree)).

0.7.0'a kadar polyctl'in adı ao'ydu (PyPI'da ao-orchestrator, GitHub'ın artık yönlendirdiği github.com/hakkisagdic/agent-orchestrator adresinde); eski addan hiçbir şey - ne komut, ne değişken, ne klasör ne de biçim - artık okunmaz ve eski bir ao'nun kurduğu proje `polyctl init` ile baştan başlar.

> **Nereden çıktı.** Haftalarca tam olarak bu döngüyle geliştirilen 30 epic'lik
> dayanıklı-iş-akışı ürününden çıkarıldı. Buradaki her koruma önce bir şey ters
> gittiği için var: tek oturumda ikinci tur başlatıp yeniden adlandırmayı yarım
> bırakan bir watchdog; tek depoda biriken on beş ajan süreci; canlı kanıtı üç saat
> bayat gösteren bir saat hatası. [`docs/lessons.md`](docs/lessons.md) listesi.
> Hiçbiri önceden tasarlanmadı.

## Dayattığı kurallar

Bunlar üslup tercihi değil. Her biri gerçek saatlere mal olmuş bir arıza.

- **Kodu yazan doğrulamaz, ve inebileceğine karar veremez.**
- **Plan okunur, yazılmaz** — bir dilimin karşısında ölçüldüğü belge, ölçülen şey
  tarafından değiştirilebiliyorsa sonraki her kontrol döngüseldir.
- **İş çekmek yetkilendirmek değildir.** Takip sistemindeki bir kayıt, birinin
  yazdığı şeydir; kimsenin doğruladığı bir şartname değil. Yazılı kabul sınırıyla
  kuyruğa girer, ya da girmez.
- **Ağır işler tek aktöre aittir.** Gate'ler makine genelinde serileştirilir; N proje
  N test suite koşturmak N kat verim değil, artık hiç bitmeyen tek bir suite'tir.
- **Yetki her tura enjekte edilen bağlamda yaşar, posta kutusunda değil.** Tıkanmış
  ajan, zaten mail okumayan ajandır.
- **`push` bu araç tarafından asla verilmez.** PR, force-push ve hook atlama da öyle.

## Ajan desteği

`polyctl` her ajanın kendi oturum deposunu okur; adaptör nerede ve hangi biçimde olduğunu
söyler.

| doğrulama | adaptörler |
|---|---|
| **full** — her yetenek gerçek koşumda sınandı | kiro, claude-code, antigravity |
| **partial** — durumu okur, bazı yetenekler sınanmadı | opencode, command-code, codex, qoder, openai-api, warp |
| **documented** — yayımlanmış dokümandan yazıldı, henüz koşulmadı | cursor-agent |
| **untested** — şema hazır, ilk koşumu bekliyor | gemini, aider, amp, copilot, amazon-q, deepseek, ollama, droid, grok, hermes, kilocode, kimi, omp, pi, pr-agent, qwen, reasonix, trae |

Warp, `oz` kullanır; polyctl, PATH üzerinde olmasa da programı `/Applications` veya
`~/Applications` altındaki Warp uygulama paketinde bulur. `polyctl init --agent warp`
yalnızca dosyalarla çalışan kurulumu yapar; Warp için MCP kaydı oluşturmaz.
Yanıtlar ve oturumlar henüz ölçülmedi; Warp inceleyici olarak uygun değildir.
[Ölçüm notu](docs/audit/2026-10-15-warp-store.md).

`polyctl adapters` bu tabloyu makinende gerçekte kurulu olanla yan yana gösterir; ve
[keyflip](https://github.com/hakkisagdic/keyflip) varsa, CLI kurulu olmasa bile hesap
olup olmadığını söyler. Yeni adaptör bir JSON dosyasıdır;
[`docs/adapters.md`](docs/adapters.md).

## Dokümantasyon

**[başlarken](docs/getting-started.md)** · **[komutlar](docs/commands.tr.md)** ·
[protokol](docs/protocol.md) · [güvenlik](docs/safety.md) · [tehdit modeli](docs/threat-model.md) · [roller](docs/roles.md) ·
[gizlilik](docs/privacy.md) · [açık bildirimi](SECURITY.md) ·
[dilimler](docs/slices.md) · [gate'ler](docs/gates.md) · [kaynaklar](docs/sources.md) ·
[adaptörler](docs/adapters.md) · [paralellik](docs/parallel.md) · [bulut](docs/cloud.md) ·
[modeller](docs/models.md) · [telegram](docs/telegram.md) · [mcp](docs/mcp.md) · [telemetri](docs/telemetry.md) ·
[yüzeyler](docs/surfaces.md) · [defter](docs/ledger.md) · [kurtarma](docs/recovery.md) ·
[keyflip](docs/keyflip.md) · [ide-eklentileri](docs/ide-extensions.md) ·
**[dersler](docs/lessons.md)**

## Durum

Bugün çalışan: [komut listesindeki](docs/commands.tr.md) her şey, gerçek bir projede günlük
kullanımda. Hâlâ şartname: belgelerin "Not built yet" diye işaretlediği her bölüm (salt okunur
lane'ler, bir lane'in rolü ve birleştirme kuyruğu bunlardan) ve projeler arası paralel
**koşum** (görünüm var; birkaç uygulayıcıyı aynı anda çalıştırmak makine gate kilidine bağlandı
ama gerçek yükte denenmedi).

polyctl'in kendi defterlerinin bu depoda güvence hakkında gösterdikleri, ölçülmüş olarak: [kanıt](docs/evidence.md).

MIT.
