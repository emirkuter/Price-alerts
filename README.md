# Emir Trade Alarm

FLNC, TSLA ve LEU için **tamamlanmış 4 saatlik mumlara göre** otomatik Telegram uyarıları.

## Dört aktif teknik gösterge
- **RSI(14):** 20 veya 15 eşiğinin aşağı yönde geçilmesi.
- **Hacim:** Son tamamlanmış 4 saatlik mum hacminin önceki 20 tamamlanmış 4 saatlik mum ortalamasının en az **2 katı** olması.
- **EMA 20/50:** EMA 20'nin EMA 50'yi yukarı veya aşağı kesmesi.
- **ATR(14):** Mevcut ATR'nin önceki 20 tamamlanmış mumdaki ATR ortalamasının **1,5 katına ilk kez ulaşması**. ATR yön belirtmez.

Aynı mumda birden fazla gösterge tetiklenirse **tek Telegram mesajında** bildirilir. Mesajda tüm dört göstergenin değerleri de yer alır. Destek/direnç kontrolleri şimdilik kapalıdır (`config.json` içinde her sembolde `support: null`).

## İlk kurulum
1. **Settings → Secrets and variables → Actions → Repository secrets** altında şunları oluştur:
   - `TWELVE_DATA_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
2. **Actions → 4-Hour Stock Alerts → Run workflow → test** ile Telegram test mesajını doğrula.
3. Gerçek veri akışı testi için **Run workflow → scan** kullan. Bu test sadece ABD normal işlem saatlerinde veri ister; yeni kapanmış mumda sinyal yoksa Telegram mesajı gönderilmez. GitHub işlem kayıtlarını kontrol et.
4. Zamanlı taramayı etkinleştirmek için **Settings → Secrets and variables → Actions → Variables** altında `ALERTS_ENABLED` değişkenini `true` yap.

GitHub yaklaşık 10 dakikalık aralıklarla tetiklemeyi dener; tetiklemeler gecikebilir. Sistem yalnızca tamamlanmış 4 saatlik mumlarla değerlendirme yapar ve aynı mum için tekrar uyarı üretmez. API kotasını Twelve Data panelinden takip et. Bu araç işlem açmaz veya stop-loss yerine geçmez.
