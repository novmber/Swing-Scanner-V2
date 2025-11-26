Swing Scanner V2, Türk Borsa endeksindeki hisseleri (BIST) Pullback ve Momentum Reversal stratejilerine göre tarayan, volatiliteye duyarlı Dinamik Risk Yönetimi sunan, yüksek performanslı web tabanlı bir analiz aracıdır.

Bu versiyon, önceki hatalar giderilerek, performansı artırmak için RAM Cache mimarisiyle tamamen yeniden yapılandırılmıştır.

✨ V2 Ana Özellikler
Bu sürüm, gerçek bir swing trader'ın aradığı düşük riskli giriş noktalarını tespit etmek üzere tasarlanmıştır:

Pullback Sinyal Motoru: Sadece trendi takip etmek yerine, fiyatın MA20 destek seviyesine geri çekildiği düşük riskli giriş bölgelerini tespit eder.

Momentum Dönüş Onayı (Reversal): Geri çekilme anında, RSI'ın aşırı satım bölgesinden veya MACD histogramının sıfır çizgisi altından yukarı dönüş sinyali vermesi beklenir.

Dinamik Stop-Loss: Hisse senedinin volatilitesine (ATR%) bağlı olarak Stop-Loss çarpanını otomatik ayarlar (1.0x'ten 2.5x'e).

İstatistiksel Hacim Onayı: Basit çarpanlar yerine Hacim Z-Score kullanarak, alımın istatistiksel olarak önemli bir hacim artışı ile desteklenip desteklenmediğini teyit eder.

Yüksek Performans (RAM Cache): Tüm tarihsel veriler başlangıçta RAM'de ön belleğe alınır, bu sayede yüzlerce sembolün taraması saniyeler içinde tamamlanır.

Parametrik Risk Yönetimi: Portföy büyüklüğünüze ve risk toleransınıza göre her hisse için kesin Önerilen Lot miktarını hesaplar.

⚙️ Kurulum ve Çalıştırma
1. Ön Gereksinimler
Bu projeyi çalıştırmak için Python 3.9 veya daha yüksek bir sürüm gereklidir.

Bash

pip install flask pandas numpy yfinance
2. Dosya Yapısı
Proje, app15.py (Ana Uygulama), indicators_v2.py (Gelişmiş Göstergeler) ve hisse listesi için hisseler.csv dosyalarından oluşur.

/Swing-Scanner-V2
├── app15.py            # Ana Flask uygulaması ve V2 sinyal motoru
├── indicators_v2.py    # Gelişmiş indikatörler: Z-Score, ATR%, MA Slope
├── hisseler.csv        # Taranacak BIST hisse kodları listesi
└── prices.db           # (Oluşturulacak) Tarihsel veri depolama
3. İlk Veri İndirme (Bootstrap)
İlk çalıştırmadan önce tüm tarihsel veriyi indirmeniz gerekir. Bu işlem, verileri prices.db dosyasına kaydeder ve RAM Cache'i doldurur.

Bash

# İlk çalıştırma ve tam veri indirme (Biraz zaman alabilir)
python app15.py --bootstrap
4. Uygulamayı Başlatma
Veri indirme işlemi bittikten sonra (veya sadece web arayüzünü açmak için) uygulamayı başlatın:

Bash

python app15.py
Tarayıcınızda http://127.0.0.1:5000 adresine gidin.

🖱️ Kullanım Talimatları
Ayarları Yapın: Arayüzdeki Portföy Büyüklüğü ve Risk/İşlem (%) alanlarını doldurun ve "Ayarları Kaydet" butonuna tıklayın.

Güncelleme: En güncel fiyatları çekmek için "Güncelle (Son Eksik Günleri Çek)" butonunu kullanın. (Bu, RAM Cache'i de otomatik günceller.)

Tara: "Tara ve Sinyalleri Göster" butonuna tıklayarak V2 Sinyal Motorunu çalıştırın.

Analiz:

GÜÇLÜ SWING SİNYALİ: Trend, Pullback, Reversal ve Hacim kriterlerinin tamamının karşılandığı en yüksek onaylı sinyaldir.

Neden (Açıklama) sütununda sinyalin hangi spesifik kriterleri karşıladığını görebilirsiniz (Örnek: Pullback: Fiyat, MA20 Destek Aralığında. | Momentum: RSI Dönüşü Onayı.).
