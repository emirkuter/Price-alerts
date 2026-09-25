# Emir Trade Alarm

FLNC, TSLA and LEU için tamamlanmış 4 saatlik mumlarla ücretsiz teknik alarm denemesi. RSI(14) 20 veya 15 altına geçiş, önceki 20 mum ortalamasına göre en az 2x hacim ve elle belirlenen destek bölgeleri. Alım/satım yapmaz; stop-loss yerine geçmez.

## Kurulum
1. GitHub deponda **Settings → Secrets and variables → Actions → Secrets → New repository secret** ekranını aç.
2. **TWELVE_DATA_API_KEY** (Twelve Data hesabındaki API key) ve **TELEGRAM_BOT_TOKEN** (BotFather'dan aldığın token) adında iki ayrı secret oluştur. Anahtarları sohbetlerde ve kodda paylaşma.
3. Telegram'da botunu aç, **Start** de ve **/start** gönder.
4. GitHub **Actions → 4-Hour Stock Alerts → Run workflow** ekranında **chat-id** seçip çalıştır. İşlem bittikten sonra çalışmanın **Run selected mode** logunda kendi sohbet ID'ni göreceksin.
5. Aynı Secrets bölümüne **TELEGRAM_CHAT_ID** isminde üçüncü secret olarak sadece kendi sohbet ID'ni ekle.
6. **Run workflow → test** seçip çalıştır. Telegram'a test mesajı ulaşmalı.
7. Test başarılıysa **Settings → Secrets and variables → Actions → Variables** ekranında **ALERTS_ENABLED** adlı variable oluştur; değeri **true** olsun. Bu yapılana kadar zamanlı tarama kapalıdır.

## Ayarlar
- **config.json** içinde FLNC, TSLA, LEU destekleri başlangıçta `null`: destek alarmı kapalı. Kendin belirlediğin seviyeleri sayısal USD değeri olarak yazabilirsin.
- Tamamlanmış 4 saatlik mumlar; RSI eşiklerinin aşağı geçilmesi, hacmin önceki 20 mum ortalamasına göre >=2x olması, belirlenmiş desteğe yukarıdan %1 yaklaşma veya altına ilk kapanış.
- GitHub yaklaşık 10 dakikada bir kontrol etmeye çalışır, ancak GitHub'ın zamanlaması ve veri sağlayıcı gecikebilir. ABD borsasının normal işlem saatleri dışında istek yapılmaz.
- İşlenen mumlar **state.json** dosyasında tutulur; aynı mum için tekrar bildirim gönderilmez. Uyarılar gerçek zamanlı değildir; çıkış/stop emirlerini aracı kurumunda tut.
- Ücretsiz Twelve Data planının geçerli kotasını kendi panelinden kontrol et. Başka servislerde de aynı API anahtarını kullanıyorsan kotan paylaşılır.
