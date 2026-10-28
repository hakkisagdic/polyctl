# Komutlar

Her `polyctl` komutu ve ne yaptığı (`pctl` kısa komuttur: aynı ayrıştırıcı, aynı çıkış kodları, aynı `--version` satırı ve yazdığın komutu adlandıran yardım ile hata iletileri). [README](../README.tr.md) her değişiklikte kullandığın beş komutla başlar; [başlarken](getting-started.md) ilk koşuyu adım adım anlatır.

| | |
|---|---|
| `polyctl status` · `polyctl watch` | tek proje: durum, telemetri, sorunlar, pano |
| `polyctl watch --all` · `polyctl fleet` | tüm projeler, insana en çok ihtiyaç duyan üstte |
| `polyctl watch --web [--port N]` | panel, pano, iniş hattı ve tüm projeler 127.0.0.1'de salt okunur sayfalar (`/`, `/board`, `/pipeline`, `/fleet`) ve JSON uç noktaları (`/api/status`, `/api/board`, `/api/pipeline`, `/api/fleet`) olarak: terminal yerine bir tarayıcı sekmesi ([surfaces.md](surfaces.md)) |
| `polyctl board` | her iş nerede; READY = `needs:` bağımlılıkları tamamlanmış kuyruk maddeleri |
| `polyctl next [--json\|--short]` | şimdi neyin beklediği ve onu hangi elin kapattığı: önce insanın maddeleri (hiç kimsenin okumadığı bir harness değişikliği, yanıtını bekleyen vekil review istemi, acil posta, açık bir kural önerisi), sonra indekslenen adayın iniş zincirinin tutmadığı ilk aşama; her biri kapatan komutla; `--short` menü çubuğu satırını, `---` ayırıcısını ve açılır menü satırlarını SwiftBar ile xbar'ın okuduğu eklenti biçiminde basar. Salt okunur: hiçbir şey çalıştırılmaz ya da kaydedilmez, insanın komutu gösterilir, yazılmaz ([surfaces.md](surfaces.md)) |
| `polyctl surfaces [install\|uninstall] swiftbar --dir <dizin>` | adlandırdığın SwiftBar ya da xbar eklenti klasörüne (`--dir` zorunludur; polyctl klasör tahmin etmez) polyctl'in çalıştırılabilir `polyctl.30s.sh` menü çubuğu eklentisini yazar ya da kaldırır, polyctl'in kendisinin olmayan bir dosyayı ezmeyi ya da silmeyi reddeder; eklenti yalnız `polyctl next --short` çalıştırır ([surfaces.md](surfaces.md)) |
| `polyctl board add ID "başlık" --acceptance "…"` | bir maddeyi yalnız kabul sınırıyla birlikte kuyruğa alır |
| `polyctl slice start <id>` · `polyctl slice block "…"` · `polyctl slice abandon --why "…"` | bir dilimi taşır: kuyruktakini başlatır ya da park edilmiş olanı sürdürür, çalışanı neyi beklediğiyle birlikte park eder, birini gerekçesiyle kayda geçirerek `rejected`'a bırakır; her taşıma `.polyctl/ledger/slices.jsonl`'de bir satırdır, dilimi bırakmak mimarın ya da bir insanın kararıdır ([slices.md](slices.md#commands)) |
| `polyctl slice status [<id>]` · `polyctl slices [--open]` | bir dilimin nerede durduğu, ne zamandan beri ve oraya nasıl geldiği, turları ve en yeni review'ının bulguları; tüm dilimler satır satır, elle taşınmış ya da silinmiş bir satır adıyla anılır |
| `polyctl verify [-p full]` | tanımlı gate'leri koştur, sonucu kaydet |
| `polyctl commit-ok [--verify]` | bu ağaç commit edilebilir mi? kanıttan karar |
| `polyctl commit -m …` · `polyctl commit-check --range A..B` | yetki verilen adayı commit et, mesajı yetkiyi adlandıran Polyctl- trailer'larıyla biter; inmiş her commit'in trailer'larının adlandırdığı ağaca sahip olduğunu `.polyctl/` gerekmeden, CI'ın koştuğu gibi denetle ([gates.md](gates.md#a-commit-names-its-grant)) |
| `polyctl hold` / `polyctl hold release --note …` | ağaçtaki tüm ajanları durdur ve durdurulmuş tut |
| `polyctl writers` / `polyctl writers --clean` | ağaçtaki canlı turlar (süreç değil tur başına bir), öksüzler ayrı; `--clean` yalnız öksüzleri durdurur |
| `polyctl fanout ok --agents N` / `polyctl fanout record …` / `polyctl fanout history` | N alt-ajanlık fan-out şimdi başlayabilir mi (üst sınır, yakın limit vuruşu, sağlayıcı penceresi); bir koşunun maliyetini kaydet |
| `polyctl gain [--since 7d] [--all] [--days 14] [--slices] [--json] [--sources] [--quota]` | polyctl'in ölçtükleri tek yüzeyde: inen dilimler ve sonuçları, review kararları, board derinliği, uygulayıcı harcaması ve araç çağrıları, watchdog uyanma ve tazelemeleri, her platformun son kayıtlı koşusu ve günlük harcama/inen dilim eğilimi; her sayı polyctl'in yazdığı bir defterden okunur, okunamayan defter sıfır gösterilmez adlandırılır, `--quota` ise hesabı yalnızca istendiğinde sorar ([telemetry.md](telemetry.md)) |
| `polyctl cost --since 24h` | koordinasyonun kendisi ne harcıyor: uygulayıcı turları sınıfa göre (ürün / analiz / tören / koordinasyon), boşa giden turlar, review sayısı; `--since`, her zaman argümanı gibi, `30m`, `2h`, `1d`, `today`, `yesterday` ya da bir tarih alır; `--usd` harcamayı pakette gelen fiyat tablosuyla ABD doları cinsinden tahmin eder ([telemetry.md](telemetry.md)) |
| `polyctl export otlp [--out <dosya>] [--attested]` | projenin defteri OTLP/JSON kodlamasında OpenTelemetry izleri olarak (tek `ExportTraceServiceRequest`): her dilim (adayı) için bir trace ve kaydedilen her gate adımı (`verification`, `review`, `grant`, `commit`) için defterin kendi zamanlarıyla ve özetten türetilmiş kimliklerle bir span; bu makinenin kontrol noktası deposunun kapsamadığı bir defteri reddeder, `--attested` yalnız doğrulanmış satırları isteyince belge bunu belirtir (`polyctl.export.attested_only=true`); `--out` dosyasına ya da standart çıktıya yazar, polyctl hiçbir yere hiçbir şey göndermez ([telemetry.md](telemetry.md#otlpjson-trace-export-polyctl-export-otlp)) |
| `polyctl features [on|off <anahtar>]` | anahtarlar ve her birinin maliyeti; hepsi kapalı = deterministik polyctl, sıfır model harcaması ([features.md](features.md)) |
| `polyctl mode [show|lite|full]` | proje modu ve her modun neyi koruyup neyi korumadığı: `lite` dayatmasız temel kurulumdur (`polyctl status`, `polyctl doctor` ve MCP durumunda `enforcement: off - lite`, reviewer yoklaması yok, commit hook'u yok, `polyctl commit` reddedilir), `--by <ad>` ile kayda geçen bir insan eylemi; `full` bağımsız reviewer rotasını ve commit hook'larını denetler, eksik olanı adlandırarak reddeder ([configuration.md](configuration.md), [safety.md](safety.md)) |
| platformlar | polyctl 0.7.0 macOS üzerinde geliştirilir ve desteklenir; Linux CI'da test paketini çalıştırır ancak henüz desteklenen bir platform değildir; Windows'ta 29 test başarısız olur (WINDOWS-LANE-0.7, docs/backlog.md) ve Windows sonraki bir sürümü bekler ([windows.md](windows.md)); testler her push ve pull request'te Ubuntu'da, macOS'ta haftalık ve WINDOWS-LANE-0.7'ye kadar Windows'ta istek üzerine koşar |
| `polyctl waive review --slice B7 --by <ad> --why …` / `polyctl catchup` | insan bir kapıyı kayıtlı biçimde atlar; catchup inen her aralığı onu yazan model ailesinden başka bir aileyle, commit mesajlarının iddia ettiklerine karşı review eder, `move-only` bir bölmeyi grant'in kaydettiği kanıtı yeniden çalıştırarak kapatır, ertelenen uyandırma/dürtmeleri yeniden oynatır. `polyctl catchup --plan` hiçbir şey yazmadan önizler ve hangilerinin kanıtla kapanacağını söyler, `polyctl catchup --limit 10` ve `polyctl catchup --slice B7` bir koşuyu sınırlar, `polyctl catchup --author-family <aile> --by <ad>` polyctl'in kaydedemediği aileyi bir insanın adlandırmasıdır, `polyctl catchup --move-only <dilimler> --by <ad>` ise waiver'lı hangi dilimlerin yalnızca kod taşıdığını bir insanın beyan etmesidir; her biri yalnızca kanıt tutarsa kapanır; `polyctl catchup --slice B7 --reviewer <aktör>` tablodaki başka bir reviewer aktörüyle review eder, böylece farklı dilimler üzerindeki koşular yan yana yürür; bir koşu başlattığı review'lar hiçbir karar vermediğinde 3, ilerlediğinde ya da yapacak bir şeyi olmadığında 0 ile çıkar |
| `polyctl pings setup [--url-env AD] [--all]` | dead man's switch: watchdog ve doctor işi birlikte ölünce alarm veren dış ping; polyctl denetimin adresini sorar ve ekrana basmaz, bir betik onu tutan değişkeni adlandırır, `polyctl pings` de pinglerin nereye gittiğini gösterir, adresin tamamını asla ([alarms.md](alarms.md)) |
| `polyctl hooks [status|install|uninstall] [--allow-shared-hooks]` / `polyctl push allow` | Git'in etkin hook yolunu çöz; roller bağımsızdır, paylaşılan/harici/global mutasyonlar komutun tamamı için açık yetki ister |
| `polyctl skill install` / `polyctl skill show` | playbook (roller, döngü, yetki, protokol, alarmlar, tüm komutlar) deponun ajanları için: Claude skill, Kiro steering, AGENTS.md |
| `polyctl remove --yes [--allow-shared-hooks]` | iki aşamalı kaldırma: dayatma etkinken `.polyctl-project` dosyasını silip commit et, HEAD ve index artık taşımayınca polyctl durumunu kaldır; yabancı/korunan hook'lara dokunma. İkinci aşama projenin zamanlanmış işlerini ve `~/.polyctl` içindeki yalnız kendi dosyalarını kaldırır, kuru koşuda her birini adıyla listeler ve kaldıramadığını adıyla söyleyip 1 ile çıkar ([watchdog.md](watchdog.md)) |
| `polyctl update [--dry-run\|--yes]` | polyctl'i kurulduğu yoldan güncelle: git klonu ileri sarılır, commit edilmemiş değişikliği varken reddedilir; Homebrew, pipx ya da uv kurulumu kendi aracıyla, pip kurulumu polyctl'i çalıştıran yorumlayıcının pip'iyle yükseltilir. Komut önce gösterilir, `--yes` ya da terminaldeki bir evet ile çalışır ([başlarken](getting-started.md#5-update-and-uninstall)) |
| `polyctl uninstall [--yes] [--purge] [--allow-shared-hooks]` | polyctl'in bu makineye kurduklarını kaldır: polyctl'in her zamanlanmış işi, kayıt defterinin bildiği her projedeki polyctl'in kendi hook'ları ve MCP dosyalarındaki `polyctl` girdisi; `--yes` olmadan kuru koşudur ve bıraktıklarını adıyla söyler - her projenin `.polyctl/` dizini, `--purge` yoksa `~/.polyctl` ve programın kendisi, onu kaldıran komutla birlikte |
| `polyctl start [--yes]` | sıfırdan çalışan, yönetilen bir projeye ilk kurulum sihirbazı: kurulu ajan CLI'larını ve model ailelerini algılar, polyctl'in bağımsızlık kuralının kabul ettiği çapraz aile uygulayıcı/reviewer çiftini önerir (ölçülmüş `verified` düzeylerini öne alır ve her çiftin neden sunulduğunu söyler), seçimi profil olarak yazar, her adımdan önce sorarak `polyctl demo`, `polyctl init`, `polyctl hooks install` ve `polyctl prove` komutlarını çalıştırır (`--yes` yalnız insan gerektirmeyen adımları koşturur) ve yalnız bir insanın atabileceği adımları (`polyctl harness seen --ask`) listeleyerek biter; asla bir insanın onayını kendisi kaydetmez ve yazılım kurmaz ([başlarken](getting-started.md)) |
| `polyctl init --profile agy-codex|codex-agy|claude-codex [--review-tier same-family|person] [--language en|tr]` | rol bloklarını ve exact `.polyctl-project` kayıt işaretini yaz, ama stage etme; tek harness'lı kurulum bir review katmanı seçer ([profiles.md](profiles.md)); `--language tr` ile polyctl'in projeye yazdıkları ve insanlara söyledikleri Türkçe olur ([configuration.md](configuration.md)) |
| `polyctl demo [--keep]` | güvence, polyctl daha deponda yokken yaklaşık bir dakikada: kendi home'u ve vekil bir reviewer'ı olan geçici bir projede hatalı bir değişikliği review, `polyctl commit-ok` ve commit hook'u reddeder, düzeltmesi Polyctl- trailer'larıyla iner; geçici klasörün dışında hiçbir şeye dokunulmaz, `--keep` o klasörü bırakır ([demo.md](demo.md)) |
| `polyctl doctor --check` | zamanlayıcı için sessiz doctor: problem başına bir satır, exit 1, alarm — `polyctl watchdog install` 15 dakikalık launchd işi, Linux'ta systemd kullanıcı zamanlayıcısı olarak kurar |
| `polyctl email setup` / `polyctl email test` | kırmızı alarm kanalı: formsubmit.co ile e-posta, sunucu yok ([alarms.md](alarms.md)) |
| `polyctl alarms` / `polyctl alarms test --level red` | canlı alarm bölümleri ve seviyeleri; test tüm kanalları çaldırır |
| `polyctl mail log` / `polyctl mail search <metin>` / `polyctl mail ack <glob>` | posta defteri: yazılan her mesaj ve ne zaman okunduğu, silindikten sonra da aranabilir |
| `polyctl watchdog explain` / `polyctl watchdog trace` | watchdog neden dürttü ya da dürtmedi: bu döngünün ve kayıtlı döngülerin ölçüm ve kararları ([watchdog.md](watchdog.md)) |
| `polyctl source import` | takip sistemindeki işleri panoya kabul et |
| `polyctl mail` · `polyctl notices` | koordinasyon mesajları; projenin ürettiği uyarılar |
| `polyctl watchdog install` | takılan ajanı yeniden başlatan launchd işi, Linux'ta systemd kullanıcı zamanlayıcısı ([watchdog.md](watchdog.md)) |
| `polyctl mcp serve [--project all]` · `polyctl a2a serve` | durumu, salt okunur kaynakları ve prompt'ları MCP istemcilerine (`--project all` kayıtlı her projeyi sunar) / A2A görevi olarak sun |
| `polyctl telegram setup` | telefona uyarı, telefondan karar; polyctl bot token'ını sorar ve ekrana basmaz, bota yazan sohbetleri bulur, `~/.polyctl/telegram.json` dosyasını kendisi yazar ([telegram.md](telegram.md)) |
| `polyctl ntfy setup --topic-url <url> [--token-env AD]` / `polyctl ntfy test` / `polyctl ntfy status` | ntfy.sh ya da kendi ntfy sunucun üzerinden telefona giden uyarılar; `~/.polyctl/ntfy.json` dosyasını 0600 kipiyle yazar, erişim token'ını yalnız `$AD` değişkeninden okur (asla argüman olmaz, ekrana basılmaz, loglanmaz) ve her uyarıyı alarm seviyesine göre öncelikle gönderir ([alarms.md](alarms.md)) |
| `polyctl digest [--days N]` | ne oldu, defterlerden okunur — "neden ilerlemiyor"un da cevabı |
| `polyctl ask` · `polyctl answer` · `polyctl decisions` | tek dokunuşla cevaplanan sorular; serbest metin hep sonda; cevap sorunun sunduğu bir harf olmalı, `polyctl answer <D-id> <harf> --change` bir cevabı değiştirir ve ilki kayıtta kalır |
| `polyctl propose "…" --why "…" [--rule-file <yol>]` · `polyctl proposals` | ajan, altında çalıştığı bir kuralı düzenlemek yerine değişikliği önerir: kanıtıyla karar defterine yazılır, bir insan `polyctl answer` ile kabul ya da ret eder; kural dosyasına hiçbir şey yazılmaz ([protocol.md](protocol.md#changing-the-rules-an-agent-proposes-a-person-decides)) |
| `polyctl note` | kutuya mimar mesajı, araç üzerinden |
| `polyctl review` | ağacı, onu yazmayan bir aktörle gözden geçir |
| `polyctl person-review --by <ad>` | bir insan stage edilmiş diff'i okur, sonra gösterilen `--digest` ile `--verdict APPROVED` ya da `NEEDS_CHANGES` kaydeder; her review gibi adaya bağlanır, `person review` diye etiketlenir, asla bir ajanın komutu değildir |
| `polyctl harness seen --by <ad>` | bir insan, bir ajanın harness'ın buradan okuduğu şeylerde - hook'lar, eklentiler, MCP sunucuları, talimatlar - ve bir rolün turunu, bir incelemeyi ya da bir avı başlatan komutta yaptığı her değişikliği okur, sonra gösterilen `--digest` ile ya da bir terminalde `--ask` ile tek adımda görüldü diye kaydeder, kendi araç onayları için olduğu gibi; o zamana kadar ağaçta hiçbir uyandırma, doldurma, dürtme, av ya da lane başlamaz; `polyctl init` ile `polyctl skill install`'ın kendi yazdıkları zaten görülmüş sayılır; asla bir ajanın komutu değildir ([safety.md](safety.md#harness-configuration-an-agent-changed-waits-for-a-person)) |
| `polyctl review --commits <aralık>` | inmiş işi sonradan review et; çıkış 3 = reviewer erişilemedi (asla verdict değil), yedekler `reviewer.fallbacks` ([roles.md](roles.md)) |
| `polyctl review --commits <aralık> --reviewer <aktör> --slice <id>` | inmiş bir aralığı projenin tablosundaki başka bir reviewer aktörüyle yeniden review et; review, aralığı indiren dilimin olarak kaydedilir ve commit mesajlarına göre yargılanır ([roles.md](roles.md)) |
| `polyctl ci review --base <rev> --reviewer <adapter> --model <model> --family <aile> --author-family <aile>` | bir pull request'in değişikliğini CI'da, kurulum gerektirmeden başka bir model ailesine review ettir: `--head`'in merge base'e eklediği commit'ler, workflow'un yazdı dediği aileye karşı tutulur; verdict ve bulgular `--summary` ve `--outputs`'a eklenir; hiçbir yetki vermez. Deponun `action.yml`'i bunu çalıştırır ([github-action.md](github-action.md)) |
| `polyctl handoff` | devralanın ihtiyacı olan her şeyi yaz ve gönder |
| `polyctl a2a-mcp serve` | MCP-only istemciden A2A ajanlarına ulaş; `.polyctl/a2a-agents.json` içindeki bir başlık değerini tutan değişkeni `${NAME}` ile adlandırır, böylece projede sır durmaz ([mcp.md](mcp.md)) |
| `polyctl prune` | biriken kayıt ve logları buda |
| `polyctl doctor` · `polyctl adapters` | bağlantıları denetle; ne destekleniyor ve ne kadar |
| `polyctl completion zsh` | polyctl'in komutlarını, seçeneklerini ve seçimlerini tamamlayan betiği yazdır; `bash`, `fish` ve `powershell` için de, [başlarken](getting-started.md#6-shell-completion) belgesindeki gibi kurulur ve `polyctl update` sonrası yeniden yazdırılır |
| `polyctl --version` | kurulu sürüm |

Hook durumu statik niyeti çalıştırılabilir dayatmadan ayırır. polyctl dayatması yalnız
HEAD'de veya etkin index'te exact `polyctl-project-v1\n` baytları bulunan kök
`.polyctl-project` ile açılır; tesadüfi `.polyctl/` dizini etkisizdir. Stage edilmiş işaret
ilk kaydı açar, stage edilmiş silme ise silme commit edilene kadar HEAD üzerinden
dayatmayı korur. Kayıtlı projede `.polyctl/config.json` geçerli, boş olmayan üst seviye
JSON nesnesi olmalıdır. polyctl en fazla 1.048.576 bayt okur ve 64'ten derin container
yapısını recursive JSON ayrıştırmasından önce reddeder; komut yönlendirmesi
öncesindeki yükleme ile commit dayatması aynı bounded sonucu kullanır. Eksik ya da
okunamayan durum tek satırlık `polyctl init --profile agy-codex` düzeltmesiyle
birlikte reddedilir.

`current-local (behavior unverified)` ve `current-scoped (behavior unverified)`
yalnız baytların polyctl'nun amaçlanan rolünü ifade ettiğini söyler. `pre-commit
execution: installed (execution proved)` ancak Git etkin hook'u yalıtılmış geçici
index ile çözüp çalıştırdığında ve polyctl aynı nonce'a bağlı reddi döndürdüğünde
yazılır. Prob gerçek index'i, worktree'yi, ref'leri veya Git object store'u
değiştirmez. Eksik, yanlış yerde, çalıştırılamayan, bayat, yabancı ya da fail-open
hook `not installed` olur; status, doctor, `doctor --check` ve init aynı sonucu
kullanır. `status`; etkin yolu, yol sınıfını, kazanan `core.hooksPath`
scope/origin/value bilgisini, track durumunu ve yanlış yerdeki polyctl biçimlerini
gösterir. Deponun git dizinine kurulan hook, onu kuran polyctl'in yolunu da taşır ve o
dosyaya yalnız `/bin/sh` PATH'te polyctl bulamadığında başvurur; bulamadığında `hooks status`
ve `doctor` bunu düzelten symlink'le birlikte söyler. Install, pre-commit ile pre-push
rollerini bağımsız ele alır; uygun pre-commit'i kurup özel pre-push'ı bayt düzeyinde
koruyabilir, push-window hook'unun kullanılamadığını söyleyebilir ve 1 dönebilir. Uygun
hedeflerden biri paylaşılan, harici ya da global/system config ile seçilmişse
install, uninstall ve remove işlemlerinin tamamı açık `--allow-shared-hooks`
olmadan reddedilir.

## Testler

Barındırılan `tests` iş akışı, main'e her push'ta ve her pull request'te paketi Ubuntu'da Python 3.9
(destek tabanı) ve 3.12 ile koşturur; macOS ve Windows her hafta ve istek üzerine koşar
(`gh workflow run tests -f os=windows-latest -f python=3.12`); Windows her hafta bir kez daha,
varsayılan bir kurulumun çalıştırdığı gibi Python'un UTF-8 kipi olmadan koşar (istek üzerine
`-f utf8=off`, [windows.md](windows.md)). Depo public olduğu için barındırılan
koşucular ücretsizdir; pre-push hook'u da push'tan önce paketi yerelde koşturur: önce push edilen
commit'lerin dokunduğu testleri, sonra bütün paketi, pytest-xdist (`dev` ekstrası) kuruluysa dört
süreçte - `POLYCTL_PREPUSH_WORKERS` kaç süreç olacağını belirler, 0 tek süreçte tutar. Bir sürüm etiketi,
yayımlamadan önce paketi yeniden koşturur. Barındırılan koşular, gerçek alt süreçler ve geçici yollarla
işletim sistemi API davranışını ve belirleyici süreç çökmelerini kapsar. Fiziksel güç kaybının,
depolama denetleyicisinin ya da dosya sisteminin - desteklenmeyen ve ağ dosya sistemleri dahil -
yeterlilik sınaması değildir.
