# `polyctl mcp serve` Uçtan Uca Doğrulama ve Kök Neden Raporu (`DOGRULAMA.md`)

**Tarih:** 15 Kasım 2026  
**Kapsam:** `polyctl mcp serve` uçtan uca protokol/oturum doğrulaması (`claude` ve `agy`), CLI–MCP araç eşdeğerliği (parity), son 30 günde 14 repoda neden hiçbir oturumun MCP araçlarını çağırmadığının kök neden analizi ve uygulanan çözüm.

---

## 1. Uçtan Uca MCP Sunucusu Doğrulaması

### 1.1 `stdio` JSON-RPC Protokolü ve Araç/Kaynak/İstem Keşfi (Otomatik Test: `tests/test_mcp_adoption.py`)

`polyctl -C <repo> mcp serve` sunucusunun MCP `2025-06-18` (`initialize` el sıkışması) ve durumsuz MCP `2026-07-28` (`server/discover` + `params._meta`) protokol davranışları `pytest tests/test_mcp_adoption.py` ile süreç içinde deterministik olarak doğrulanmaktadır:

| JSON-RPC Metodu | İstek Parametresi | Doğrulanan Sonuç | Durum |
|---|---|---|---|
| `initialize` | `protocolVersion: "2025-06-18"` | `protocolVersion: "2025-06-18"`, `serverInfo: {"name": "polyctl"}` | Başarılı |
| `server/discover` | `_meta: {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}` | `resultType: "complete"`, `supportedVersions: ["2026-07-28", "2025-06-18"]` | Başarılı |
| `tools/list` (rolsüz / `--role architect`) | `{}` | 15 araç (`polyctl_status`, `polyctl_board`, `polyctl_next`, `polyctl_candidate`, `polyctl_notices`, `polyctl_fleet`, `polyctl_inbox`, `polyctl_ack`, `polyctl_report`, `polyctl_ask`, `polyctl_decisions`, `polyctl_propose`, `polyctl_fanout`, `polyctl_watchdog`, `polyctl_verify`) | Başarılı |
| `tools/list` (`--role implementer`) | `{}` | 13 araç (`polyctl_candidate` ve `polyctl_fleet` hariç tüm uygulayıcı araçları) | Başarılı |
| `tools/list` (`--role reviewer`) | `{}` | 3 salt-okunur araç (`polyctl_status`, `polyctl_board`, `polyctl_candidate`) | Başarılı |
| `resources/list` | `{}` | 4 kaynak (`polyctl://<proje>/board`, `roles`, `ledger`, `decisions`) | Başarılı |
| `prompts/list` | `{}` | 3 istem (`status`, `land-slice`, `stuck`; `--role implementer` için `status` ve `stuck`) | Başarılı |

---

### 1.2 Claude Code (`claude`) Oturumunda İstemci Davranışı (Manuel İstemci Doğrulaması)

Aşağıdaki adımlar, `claude` ikilisinin kurulu olduğu geliştirici makinesinde `.mcp.json` proje kapsamı ile `local` kapsam arasındaki onay farkını doğrular (harici `claude` ikilisi gerektirdiğinden çevrimdışı birim testlerinde değil, istemci ortamında çalıştırılır):

```sh
polyctl -C <repo> init --agent claude-code
claude mcp get polyctl
claude mcp add -s local polyctl -- polyctl -C <repo> mcp serve --role implementer
claude mcp get polyctl
```

1. **Varsayılan `.mcp.json` (Proje Kapsamı):**
   - `skillkit.register_mcp` (`src/polyctl/skillkit.py`), `claude-code` adaptörü için `<repo>/.mcp.json` dosyasına `{"mcpServers": {"polyctl": {"command": "<exe>", "args": ["-C", "<repo>", "mcp", "serve", "--role", "<role>"]}}}` kaydını yazar (bkz. `tests/test_mcp_adoption.py`).
   - Claude Code güvenlik modeli gereği `.mcp.json` içindeki proje kapsamlı sunucuları kullanıcı etkileşimli olarak onaylayana kadar `Status: ⏸ Pending approval (run claude to approve)` durumunda tutar ve `claude -p` (headless) turlarda başlatmaz.
2. **Etkileşimli Onay veya Yerel Kapsam (`claude mcp add -s local`):**
   - Kullanıcı `claude` içinde `.mcp.json` onayını verdiğinde veya aynı rol kapsamlı komutu `local` kapsamda kaydettiğinde sunucu `Status: ✔ Connected` (`Type: stdio`) durumuna geçer.

---

### 1.3 Antigravity (`agy`) Oturumunda İstemci Davranışı (Manuel İstemci Doğrulaması)

Aşağıdaki adımlar, `agy` ikilisinin kurulu olduğu geliştirici makinesinde kullanıcı kapsamlı MCP kaydını ve canlı araç çağrısını doğrular:

```sh
agy mcp add polyctl-e2e -- polyctl -C <repo> mcp serve --role implementer
agy mcp list
agy --print="Call polyctl_status, polyctl_board, and polyctl_inbox and return a compact JSON summary." --dangerously-skip-permissions --output-format=json
agy mcp remove polyctl-e2e
```

1. **Adaptör Bildirimi (`src/polyctl/adapters/antigravity.json`):**
   - `antigravity.json` içinde `"subcommands": {"mcp": ["agy", "mcp"]}` tanımlıdır ancak proje içi `mcp.file` veya `mcp.manual` alanı bulunmaz (`tests/test_mcp_adoption.py` içinde doğrulanır). Bu nedenle `polyctl init` çalışırken `agy` için otomatik MCP kaydı yazılmaz.
2. **Kullanıcı Kapsamında Kayıt Sonrası Bağlantı:**
   - `agy mcp add` ile kullanıcı kapsamına eklendiğinde `agy` oturumu `polyctl mcp serve` sunucusuna `stdio` üzerinden bağlanır ve `polyctl_status`, `polyctl_board`, `polyctl_inbox` araçlarını tek turda çağırabilir.

---

### 1.4 Mail, Board, Review/Candidate ve Status Araçlarının CLI ile Eşdeğerlik (Parity) Karşılaştırması

Aşağıdaki eşdeğerlik ilişkilerinin tamamı `tests/test_mcp_adoption.py` içinde gerçek CLI komutlarıyla (`cli.main`) karşılaştırılarak doğrulanmaktadır:

| Alan | MCP Aracı | CLI Komutu | Eşdeğerlik Durumu ve Yapısal Karşılaştırma |
|---|---|---|---|
| **Durum (Status)** | `polyctl_status` (`mcp.status_payload`) | `polyctl status --json` (`cli._status_json`) | **Aynı Durum Kaynağı, Farklı Üst Zarf:** `polyctl_status`, `mcp.status_payload(cfg)` üzerinden 27–28 üst düzey alanı (`project`, `root`, `state`, `adapter`, `doing`, `enforcement`, `head`, `dirty_files`, `mailbox`, `mode`, `reviews`, `turns`, `unpushed` vb.) döner. `polyctl status --json` ise aynı durum verisini `{project, root, at, implementer, workspaces, telemetry, problems, push_guard, returned_reviews, reviews, rounds, throughput, repository, mail, board, messages}` zarfıyla döner. |
| **Pano (Board)** | `polyctl_board` (`mcp.board_payload`) | `polyctl board` ve `polyctl board ready` (`cli.cmd_board`) | **Aynı Pano Durumu (`A.board_states`, `A.board_ready`):** `polyctl_board`, `{states, counts, ready, problems, a2a}` JSON nesnesini döner; `polyctl board` aynı `A.board_states(root)` verisini metin tablosu (`_board_lines`) olarak, `polyctl board ready` ise aynı `A.board_ready(root)` dilim kimliklerini satır satır basar. |
| **Sıradaki Adım (Next)** | `polyctl_next` (`mcp.next_payload`) | `polyctl next --json` (`cli.cmd_next`) | **Aynı `next_steps.collect(cfg)` Çıktısı:** `polyctl next --json` `{project, person: [...], implementer: [...]}` dönerken `polyctl_next` aynı öğeleri `{project, counts: {person, implementer}, items: person + implementer}` olarak döner (`mcp_next["items"] == cli_next["person"] + cli_next["implementer"]`). |
| **Posta Kutusu (Mail)** | `polyctl_inbox`, `polyctl_ack`, `polyctl_report` | `polyctl mail list`, `polyctl mail ack`, `polyctl mail send` | **Aynı Dosya ve Defter Kaynağı:** Aynı `agent-mail/` dosyalarını ve `.polyctl/ledger/mail.jsonl` defterini kullanır. `polyctl_inbox` ve `polyctl_ack`, güvenliği sağlamak için yalnızca sunucunun rolüne (`--role` veya `POLYCTL_ROLE`) adreslenen mesajları listeler ve tüketir (`A.addressed_to`). |
| **Kararlar (Decisions)** | `polyctl_ask`, `polyctl_decisions` | `polyctl ask`, `polyctl decisions` | **Aynı Karar Defteri (`A.ask`, `A.decisions`):** `polyctl_ask` ile açılan karar sorusu `.polyctl/ledger/decisions.jsonl` içine yazılır ve hem `polyctl_decisions` hem de `polyctl decisions` çıktısında aynı kimlik (`D-...`) ve seçeneklerle görünür. |
| **İnceleme ve Aday (Review / Candidate)** | `polyctl_candidate`, `polyctl_verify` | `polyctl review`, `polyctl verify`, `polyctl commit-ok` | **Mimari Yetki Ayrımı:** Yetki sınırı (`Authority stays in the CLI`) gereği `polyctl review`, `polyctl person-review`, `polyctl commit-ok` ve `polyctl commit` kasıtlı olarak MCP aracına dönüştürülmemiştir. Bunun yerine `polyctl_candidate`, `polyctl review` komutunun yargıladığı sahnelenmiş adayı (`A.index_candidate(root)` -> `slice`, `title`, `boundary`, `candidate`, `context`) döner; `polyctl_verify` ise `--allow-verify` ile başlatıldığında `polyctl verify` kapılarını çalıştırır. |

---

## 2. MCP Araçlarının Çağrılmamasının Kök Nedenleri

`.mcp.json` içinde `polyctl mcp serve` kaydı bulunan repolarda ajanların MCP yerine CLI kullanmasının **3 kök nedeni** vardır:

1. **Kök Neden 1 — İstemci Onay ve Kayıt Engeli (`claude` `Pending approval` ve `agy` Kayıt Eksikliği):**
   - **Claude Code (`claude`):** `polyctl init`, kaydı proje içi `.mcp.json` dosyasına yazar. Claude Code, `.mcp.json` içindeki sunucuları kullanıcı etkileşimli olarak onaylayana kadar `Pending approval` durumunda tutar; etkileşimli onay verilmediğinde veya `claude -p` (headless) turlarda `polyctl mcp serve` süreci başlatılmaz. Ayrıca inceleyici (`reviewer`) ve `hunt` turları `--strict-mcp-config` bayrağıyla (`src/polyctl/adapters/claude-code.json`) çalıştığından `.mcp.json` dosyasını yüklemez.
   - **Antigravity (`agy`):** `src/polyctl/adapters/antigravity.json` dosyasında `mcp` bloğu bulunmadığı için `polyctl init` çalışırken `agy` için otomatik MCP kaydı oluşturulmaz.

2. **Kök Neden 2 — Playbook (`SKILL.md`) ve `RULE_POINTER` Yönergelerinin Önce CLI Komutlarını Öğretmesi:**
   - `skillkit.RULE_POINTER` (`start every turn with polyctl status and the mailbox`) ve `src/polyctl/skill/SKILL.md` (`## 3. The loop, per slice`, `## 5. Measure before concluding`, `## 12. Commands`) uygulayıcıya durum, pano ve karar sorguları için doğrudan `polyctl status`, `polyctl board`, `polyctl next`, `polyctl decisions` kabuk komutlarını öğretmekteydi.
   - MCP araçlarını doğrudan öğreten `STEERING_COORD` dosyası yalnızca `directives.coordination` tanımlayan adaptörlere (yalnızca Kiro: `.kiro/steering/polyctl-coordination.md`) yazılmakta, Claude Code ve Antigravity'ye yazılmamaktaydı.

3. **Kök Neden 3 — Yetki Adımlarının Kabuk (`Bash`) Gerektirmesi ve Mimar İzin Kısıtı:**
   - `polyctl slice start`, `polyctl verify`, `polyctl review`, `polyctl commit-ok` ve `polyctl commit` adımları tasarımsal olarak CLI'da tutulduğundan (ve `claude-code.json` içindeki `architect_tools` izin listesi yalnızca `Bash(polyctl ...)` kurallarını içerdiğinden), ajanlar kabuk üzerinden CLI komutlarını çalıştırmaya devam etmiştir.

---

## 3. Öneri ve Uygulanan Çözüm

Uygulayıcı ajanların MCP sunucusu bağlıyken okuma ve koordinasyon adımlarında gerçekten izin verilen MCP araçlarını kullanması ve kurulumda `.mcp.json` onay / `--no-mcp` seçeneklerinin açık olması için aşağıdaki değişiklikler uygulanmıştır:

1. **Playbook (`src/polyctl/skill/SKILL.md`) ve `RULE_POINTER` (`src/polyctl/skillkit.py`) Güncellemesi:**
   - `RULE_POINTER` içine tur başlangıcında `polyctl_status` (veya `polyctl status`) ve `polyctl_inbox` (posta kutusu) kullanımı eklendi.
   - `SKILL.md` içindeki **Bölüm 3 (The loop, per slice)** ve **Bölüm 5 (Measure before concluding)** güncellenerek uygulayıcının izin verilen MCP araçlarını (`polyctl_status`, `polyctl_board`, `polyctl_next`, `polyctl_inbox`, `polyctl_ack`, `polyctl_report`, `polyctl_decisions`, `polyctl_notices`, `polyctl_watchdog`) kabuk çıktısı filtrelerinden etkilenmemek için öncelikli kullanması tanımlandı; inceleyicinin salt-okunur araçları (`polyctl_status`, `polyctl_board`, `polyctl_candidate`) **Bölüm 9**'da açıklandı.
2. **Claude Code Onay ve `--no-mcp` Kurulum Yönergeleri (`skillkit.next_steps` & `SKILL.md` Bölüm 9):**
   - `polyctl init` sonrasındaki `skillkit.next_steps` çıktısına ve `SKILL.md` Bölüm 9'a, Claude Code'da `.mcp.json` içindeki rol kapsamlı (`--role`) kaydın yüklenmesi için başlangıçta onaylanması (`claude` içinde onay veya rol kapsamlı komutun `claude mcp add -s local` ile eklenmesi), Antigravity (`agy`) için `agy mcp add` kullanımı ve CLI/dosya tabanlı kurulum isteyen repolar için mevcut `polyctl init --no-mcp` seçeneği eklendi.
3. **Uçtan Uca Otomatik Testler (`tests/test_mcp_adoption.py`):**
   - `polyctl mcp serve` JSON-RPC el sıkışması (`2025-06-18` ve `2026-07-28`), rol bazlı araç listesi (`architect`, `implementer`, `reviewer`), `skillkit.register_mcp` `.mcp.json` rol kaydı, CLI–MCP çıktı eşdeğerliği (`status` tüm ortak durum alanları, `board`, `next`, `candidate`, `inbox`, `ack`, `report`, `ask`, `decisions`) ve playbook/yönerge MCP kuralları otomatik test altına alındı.
