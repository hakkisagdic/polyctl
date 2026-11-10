# Dilimler

[English](slices.md) | **Türkçe**

Bir **dilim**, bir aktörün tek bir çalışma hattında tamamladığı, kabul sınırı
yazılmış iş birimidir. Turlar, maliyet, kararlar ve commit'ler bu birime bağlanır.

## İş türleri

Pano satırındaki `type:` alanı `bugfix`, `poc`, `feature` veya `enterprise`
olabilir. Alan yoksa varsayılan **feature**'dır. Pano varsayılan türü de gösterir.

```bash
polyctl slice add B8 "kabul hatasını düzelt" --acceptance "yinelenen talepler reddedilir" --type bugfix
polyctl slice edit B8 --type feature
polyctl slice add P1 "önbellek deneyi" --acceptance "gecikmeyi ölç" --type poc
```

`slice add`, `board add` ile aynı kabul sınırı ve bağımlılık kontrollerini kullanır;
`--needs` ve `--role` seçeneklerini de kabul eder. `slice edit`, durumu, başlığı ve
kabul sınırını koruyarak türü değiştirir. Dilim eklemek veya türünü değiştirmek
mimarın ya da bir insanın kararıdır (uygulayıcıya reddedilir) ve kontrol noktası
onaylı opt-in defterine kaydedilir; pano satırını elle düzenlemek kayıtlı türü
düşüremez. Tür değişince doğrulama ve incelemeyi yeniden çalıştırın: kanıtlar ve
commit izni etkin profile bağlıdır.

**Mod yaptırımı, tür kontrolün kapsamını belirler.** Lite modunda yaptırım yoktur;
full modunda `poc` dahil her dilim türü için çapraz aile incelemesi ve `commit-ok`
korunur. Açıkça çağrılan doğrulama ve inceleme her iki modda da türün kapsamını
kullanır:

| Tür | Doğrulama profili | İnceleme | Boyut | Spec | İncelemeci aileleri |
|---|---|---|---|---|---|
| bugfix | quick | staged diff ve kabul sınırı; çevre kaynak kodu, aday çalışma ağacı ve bölüm/mercek geçişleri yok | kapalı | kapalı | 1 |
| poc | quick | mevcut tam inceleme | kapalı | kapalı | 1 |
| feature | mevcut varsayılan veya açık `-p` | mevcut tam inceleme | mevcut eşik | kapalı | 1 |
| enterprise | full | tam inceleme, ardından başka bir ailenin tüm sınırı incelemesi | mevcut eşik | zorunlu | 2 |

Doğrulama tanımlı komutları çalıştırır; bugfix hangi testlerin atlanabileceğini
tahmin etmez. İncelemenin girdi boyutu sınırı ve tehdit modeli geçerlidir.
`bugfix`, `poc` ve `feature` mevcut inceleme anahtarını ve kayıtlı muafiyet
kurallarını korur. `enterprise` için iki model ailesi ve başarılı spec kontrolü
zorunludur; inceleme anahtarının kapatılması veya inceleme muafiyeti bunların
yerine geçmez.

`.polyctl/config.json` içindeki isteğe bağlı `work_types` tablosu varsayılanları
değiştirir. Eksik satır ve alanlar aşağıdaki değerleri alır:

```json
{
  "work_types": {
    "bugfix": {"verify": "quick", "review": "diff", "size": false, "spec": false, "reviewer_families": 1},
    "poc": {"verify": "quick", "review": "full", "size": false, "spec": false, "reviewer_families": 1},
    "feature": {"verify": "default", "review": "full", "size": true, "spec": false, "reviewer_families": 1},
    "enterprise": {"verify": "full", "review": "full", "size": true, "spec": true, "reviewer_families": 2}
  }
}
```

`verify`, `.polyctl/gates.json` içindeki profil adıdır; `default` mevcut seçim
kuralını korur. Adı verilen profil zorunludur; `-p` başka bir profil seçemez.
Diğer alanlar kapsamı artırabilir, türün asgari kontrollerini kaldıramaz.
Bilinmeyen tür, geçersiz değer veya farklı türlerde çalışan dilimler reddedilir.

Enterprise mevcut incelemeci zincirinden (`reviewer.fallbacks` veya yetenek
matrisi) uygun iki ayrı model ailesi seçer. İki yanıt tek incelemede kaydedilir;
herhangi birinin engelleyici bulgusu reddetmeye yeter. İkinci yanıt geçersizse
veya alınamazsa yeni onay oluşmaz. Bir kişinin incelemesi iki model ailesinin
yerine geçmez. Varsayılan feature profili dışındaki profiller şimdilik taşınan stand-in
yanıtları yerine yapılandırılmış incelemecileri kullanır.

AIDLC-2 bağlantısı, seçilen doğrulama profilindeki `spec` adlı kontroldür.
Çalışıp geçmesi gerekir; AIDLC-1 spec uygulamasını sağlamaz. Bu kontrol
tanımlanana kadar enterprise doğrulaması komut çalıştırmadan reddedilir.
Başka bir tür `spec` alanını etkinleştirirse aynı koşul geçerlidir.

## Kabul sınırı ve yaşam döngüsü

Her dilim başlamadan önce yazılı bir kabul sınırı taşır. Kısa sınır satırdaki
`acceptance:` alanındadır; uzun sınır commit'e sabitlenmiş bir dosyada tutulur.
`polyctl slice start` hazır işi başlatır, `polyctl slice block` nedeni ile
park eder, `polyctl slice abandon` vazgeçilen işi kayıtta tutar.
`polyctl slice status` ve `polyctl slices` durumu ve geçmişi gösterir.
Mevcut boyut eşikleri, tur bütçesi, yaşam döngüsü ve saf taşıma ispatının
ayrıntıları [İngilizce dilim kılavuzundadır](slices.md).
