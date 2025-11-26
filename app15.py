# app15.py
#!/usr/bin/env python3
"""
Swing Scanner - Gelişmiş Sinyal Motoru V2 (Pullback + Reversal + Dinamik SL + Cache)

Geliştirmeler:
1.  KRİTİK HATA DÜZELTME: CLI fonksiyonları (bootstrap/update) kodun başına taşındı.
2.  PERFORMANS: Tüm tarihsel veri, tarama hızını artırmak için RAM'de ön belleğe alındı (DATA_CACHE).
3.  SİNYAL MANTIĞI V2:
    * Trend Takibi yerine "MA20'ye Geri Çekilme (Pullback)" eklendi.
    * "Momentum Dönüşü (Reversal)" (RSI/MACD) onayı eklendi.
    * MA20 Eğimi (Slope) pozitif olma zorunluluğu eklendi.
    * Hacim onayı için basit çarpan yerine "Volume Z-Score" kullanıldı.
4.  RİSK YÖNETİMİ: Volatiliteye (ATR%) göre dinamik Stop-Loss çarpanı eklendi.
5.  UX: Tabloda yeni sinyal nedenleri ve metrikler gösterildi.
"""

import os
import csv
import sqlite3
import argparse
import datetime
import threading
import logging
from typing import Optional, Tuple, Dict, Any

import pandas as pd
import numpy as np 
import yfinance as yf
from flask import Flask, render_template_string, request, redirect, url_for, flash, session

# V2 İndikatör Modülünü import et
try:
    from indicators_v2 import calculate_rsi, calculate_macd, calculate_atr, calculate_volume_zscore, calculate_ma_slope
except ImportError:
    print("HATA: indicators_v2.py dosyası bulunamadı. Lütfen app15.py ve indicators_v2.py'nin aynı klasörde olduğundan emin olun.")
    exit()

# ---------- AYARLAR ----------
DB_FILE = "prices.db"
SYMBOLS_CSV = "hisseler.csv"
AUTO_ADJUST = True
VOLUME_ZSCORE_THRESHOLD = 1.0 # Yüksek hacim için minimum Z-Score
MA_SLOPE_PERIOD = 5 # MA eğimi için 5 günlük değişim

# Yeni Risk Yönetimi Ayarları (Başlangıç Değerleri)
DEFAULT_RISK_PER_TRADE = 0.025  # %2.5 sermaye riski
DEFAULT_PORTFOLIO_SIZE = 50000.00 # Örnek Portföy Büyüklüğü (TL)

# RAM Cache için global değişken
DATA_CACHE: Dict[str, pd.DataFrame] = {}

# ---------- LOGLAMA AYARLARI ----------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger('SwingScanner')

# Flask uygulaması
app = Flask(__name__)
app.secret_key = os.urandom(24) 

# ---------- CLI UTILITIES (KRİTİK HATA DÜZELTME) ----------
# CLI fonksiyonları, NameError hatasını önlemek için main bloğundan önce tanımlanmalıdır.

def load_symbols_from_csv() -> list:
    if not os.path.exists(SYMBOLS_CSV):
        return []
    syms = []
    with open(SYMBOLS_CSV, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row: continue
            s = row[0].strip().upper()
            if s == "": continue
            if s.endswith(".IS"): s = s[:-3]
            syms.append(s)
    # Tekrar eden sembolleri kaldırma
    return list(set(syms))

def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL NOT NULL,
            high REAL, 
            low REAL,  
            volume INTEGER,
            UNIQUE(symbol, date)
        );
    """)
    conn.commit()
    conn.close()

def get_historical_data_from_db(symbol: str) -> Optional[pd.DataFrame]:
    """Veriyi doğrudan DB'den çeker."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    try:
        df = pd.read_sql_query(
            "SELECT date, close, high, low, volume FROM prices WHERE symbol=? ORDER BY date ASC",
            conn,
            params=(symbol + ".IS",),
            index_col='date',
            parse_dates=['date']
        )
        if df.empty:
            return None
        return df.sort_index()
    finally:
        conn.close()

def load_all_data_to_cache():
    """Tüm sembol verilerini DB'den RAM'deki DATA_CACHE'e yükler (Performans için kritik)."""
    global DATA_CACHE
    syms = load_symbols_from_csv()
    logger.info("RAM Cache yükleniyor...")
    
    new_cache = {}
    for s in syms:
        df = get_historical_data_from_db(s)
        if df is not None:
            # Sadece analiz için gerekli olan son 250 günü tutabiliriz (isteğe bağlı)
            new_cache[s] = df.tail(300) 
            
    DATA_CACHE = new_cache
    logger.info(f"RAM Cache yüklendi. {len(DATA_CACHE)} sembol hazır.")

def fetch_and_store(symbol: str, start: Optional[str] = None, end: Optional[str] = None) -> Tuple[bool, str]:
    # (Önceki versiyondan alınmıştır, toplu ekleme içerir)
    ticker = symbol + ".IS"
    df = pd.DataFrame() 
    try:
        if start and end:
            df = yf.download(ticker, start=start, end=end, auto_adjust=AUTO_ADJUST, progress=False)
        else:
            df = yf.download(ticker, period="max", interval="1d", auto_adjust=AUTO_ADJUST, progress=False)
    except Exception as e:
        logger.error(f"Symbol {symbol}: yf download error: {e}")
        return False, f"yf download error: {e}"

    if df.empty:
        return False, "No data returned from yfinance."

    try:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        
        df2 = df.reset_index() 
        required_cols = ["Date", "Close", "Volume", "High", "Low"] 
        df2 = df2[required_cols].rename(
            columns={"Date": "date", "Close": "close", "Volume": "volume", "High": "high", "Low": "low"}
        )
        df2.dropna(subset=['date', 'close', 'high', 'low'], inplace=True) 
        df2['date'] = df2['date'].dt.strftime("%Y-%m-%d")
        df2['symbol'] = ticker
        
    except Exception as e:
        logger.error(f"Symbol {symbol}: Data processing error: {e}")
        return False, f"Data processing failed: {e}"

    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    try:
        inserted_rows = len(df2)
        # Toplu Ekleme (method='multi') kullanıldı
        df2.to_sql('prices', conn, if_exists='append', index=False, method='multi')
        
        # Güncel veriyi ön belleğe de ekle
        load_all_data_to_cache() 
        return True, f"ok inserted: {inserted_rows} rows attempted" 
    except Exception as e:
        if "UNIQUE constraint failed" not in str(e):
             logger.error(f"Symbol {symbol}: to_sql error: {e}")
             return False, f"to_sql error: {e}"
        load_all_data_to_cache() 
        return True, "ok (some were already there or failed unique constraint)" 
    finally:
        conn.close()

def get_last_db_date(symbol: str) -> Optional[str]:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("SELECT date FROM prices WHERE symbol=? ORDER BY date DESC LIMIT 1", (symbol + ".IS",))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return row[0]

def update_symbol_prices(symbol: str):
    last = get_last_db_date(symbol)
    today = datetime.date.today().strftime("%Y-%m-%d")
    
    if last is None:
        logger.info(f"Symbol {symbol}: Full bootstrap needed.")
        return fetch_and_store(symbol)
        
    if last >= today:
        return True, "cache up-to-date"

    try:
        start_dt = (datetime.datetime.strptime(last, "%Y-%m-%d") + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        end_dt = (datetime.datetime.strptime(today, "%Y-%m-%d") + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        logger.error(f"Symbol {symbol}: Date parse error for last date: {last}")
        return False, "Date parse error"
        
    logger.info(f"Symbol {symbol}: Updating from {start_dt} to {end_dt}")
    return fetch_and_store(symbol, start=start_dt, end=end_dt)

# CLI Fonksiyonları
def cli_bootstrap_all():
    syms = load_symbols_from_csv()
    total = len(syms)
    logger.info(f"CLI Bootstrap: {total} sembol indiriliyor...")
    for i, s in enumerate(syms, 1):
        ok, msg = fetch_and_store(s)
        logger.info(f"[{i}/{total}] {s} : {msg}")
    logger.info("CLI Bootstrap tamamlandı. RAM Cache yüklendi.")

def cli_update_all():
    syms = load_symbols_from_csv()
    logger.info(f"CLI Update: {len(syms)} sembol güncelleniyor...")
    for s in syms:
        ok, msg = update_symbol_prices(s)
        logger.info(f"{s} : {msg}")
    logger.info("CLI Update tamamlandı. RAM Cache güncellendi.")

# ---------- GELİŞMİŞ SİNYAL MOTORU V2 ----------

def get_dynamic_atr_multiplier(atr_percent: float) -> float:
    """Volatiliteye (ATR%) göre dinamik SL çarpanını belirler."""
    if atr_percent < 2.0:
        return 2.5 # Düşük Volatilite: Stop Loss'u uzat
    elif atr_percent > 5.0:
        return 1.0 # Yüksek Volatilite: Riski yönetmek için Stop Loss'u kısalt
    else:
        return 1.5 # Normal Volatilite

def swing_signal_engine_v2(symbol: str, risk_per_trade: float, portfolio_size: float) -> Tuple[str, Optional[Dict[str, Any]]]:
    
    # 1. PERFORMANS: Veriyi RAM Cache'ten al
    if symbol not in DATA_CACHE or DATA_CACHE[symbol].shape[0] < 200:
        return "Veri Eksik (< 200 gün)", None
        
    df = DATA_CACHE[symbol].copy()
    
    # Tüm göstergeleri hesapla
    df['ma20'] = df['close'].rolling(window=20).mean()
    df['ma50'] = df['close'].rolling(window=50).mean()
    df['ma200'] = df['close'].rolling(window=200).mean()
    
    df = calculate_rsi(df)
    df = calculate_macd(df)
    df = calculate_atr(df) # atr_percent de hesaplandı
    df = calculate_volume_zscore(df)
    df = calculate_ma_slope(df, ma_period=20, slope_period=MA_SLOPE_PERIOD)

    if df.shape[0] < 2:
        return "Yeterli İndikatör Verisi Yok", None
        
    last = df.iloc[-1]
    prev = df.iloc[-2] # Reversal için bir önceki güne ihtiyacımız var

    price = last['close']
    ma20 = last['ma20']
    ma50 = last['ma50']
    ma200 = last['ma200']
    rsi = last['rsi']
    macd_hist = last['macd_hist']
    atr = last['atr']
    atr_percent = last['atr_percent']
    volume_zscore = last['volume_zscore']
    ma20_slope = last['ma20_slope']
    
    signal_reason = []
    
    # --- KRİTER 1: ANA TREND ONAYI (Trend Following) ---
    is_trend_ok = (price > ma20) and (ma20 > ma50) and (ma50 > ma200)
    is_ma20_up = ma20_slope > 0 # MA20'nin son 5 gündeki eğimi pozitif mi?
    
    if not is_trend_ok:
        signal_reason.append("Trend: MA'lar doğru sıralanmamış.")
        
    if is_trend_ok and is_ma20_up:
        signal_reason.append("Trend: **MA Sıralaması ve MA20 Eğimi Pozitif.**")
        
    # --- KRİTER 2: PULLBACK (Düşük Riskli Giriş) ---
    # Fiyatın MA20'ye %1-%3 yaklaşması (Swing Pullback sinyali)
    pullback_min = ma20 * 0.98 
    pullback_max = ma20 * 1.02 # Fiyat MA20'nin en fazla %2 üzerinde olabilir
    
    is_pullback_ok = (price >= pullback_min) and (price <= pullback_max)
    
    if is_pullback_ok:
        signal_reason.append("Pullback: **Fiyat, MA20 Destek Aralığında.**")
    else:
        signal_reason.append("Pullback: Fiyat MA20'den uzak.")
        
    # --- KRİTER 3: MOMENTUM DÖNÜŞÜ (Reversal) ---
    # 1. RSI Reversal: RSI 50'nin altında ve bir önceki güne göre yükseliyor.
    is_rsi_reversal = (rsi < 55) and (rsi > prev['rsi']) 

    # 2. MACD Reversal: MACD Histogramı dünden bugüne pozitif bölgeye geçmiş.
    is_macd_reversal = (macd_hist > 0) and (prev['macd_hist'] < 0)
    
    is_momentum_ok = is_rsi_reversal or is_macd_reversal
    
    if is_momentum_ok:
        if is_rsi_reversal: signal_reason.append("Momentum: **RSI Dönüşü Onayı.**")
        if is_macd_reversal: signal_reason.append("Momentum: **MACD 0 Çizgisi Kırılımı.**")
    else:
        signal_reason.append("Momentum: Dönüş sinyali yok.")
        
    # --- KRİTER 4: HACİM ONAYI (Volume Z-Score) ---
    is_volume_spike = (volume_zscore >= VOLUME_ZSCORE_THRESHOLD)
    
    if is_volume_spike:
        signal_reason.append(f"Hacim: **İstatistiksel Yükseliş (Z>{VOLUME_ZSCORE_THRESHOLD}).**")
    else:
        signal_reason.append("Hacim: Normal seviyede.")
        
    # --- LOT HESAPLAMA (Dinamik SL Çarpanı) ---
    
    dynamic_multiplier = get_dynamic_atr_multiplier(atr_percent)
    stop_loss = np.nan
    recommended_lot = np.nan
    
    if pd.notna(atr) and atr > 0:
        # Dinamik Stop-Loss: Fiyat - (Dinamik ATR Çarpanı * ATR)
        stop_loss = round(price - (dynamic_multiplier * atr), 2)
        
        risk_amount = portfolio_size * risk_per_trade
        risk_per_lot = price - stop_loss
        
        MIN_RISK_PER_LOT = 0.01 
        if risk_per_lot > MIN_RISK_PER_LOT: 
             recommended_lot = int(risk_amount / risk_per_lot)
        else:
             recommended_lot = 0 
    
    # --- FİNAL SİNYAL KARARI ---
    
    is_strong_swing_signal = is_trend_ok and is_ma20_up and is_pullback_ok and is_momentum_ok and is_volume_spike
    
    final_status = "Uygun Değil"
    if is_strong_swing_signal:
        final_status = "GÜÇLÜ SWING SİNYALİ (Pullback+Reversal)"
    elif is_trend_ok and is_pullback_ok and is_momentum_ok:
        final_status = "Orta SWING SİNYALİ (Hacim Eksik)"
    elif is_trend_ok:
        final_status = "Trend Pozitif (Giriş Kriterleri Eksik)"
        
    # --- SONUÇ SÖZLÜĞÜNÜ OLUŞTUR ---
    vals = {
        "symbol": symbol, 
        "price": price,
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "rsi": rsi,
        "macd_hist": macd_hist,
        "volume_zscore": volume_zscore, 
        "ma20_slope": ma20_slope,
        "atr": atr, 
        "atr_percent": atr_percent,
        "dynamic_multiplier": dynamic_multiplier,
        "stop_loss": stop_loss, 
        "recommended_lot": recommended_lot, 
        "analysis_date": str(df.index[-1].date()),
        "signal_reason": " | ".join(signal_reason),
        "is_strong_signal": is_strong_swing_signal
    }

    return final_status, vals

# ---------- Flask routes (TEMPLATE ve Mantık Güncellendi) ----------

TEMPLATE_INDEX = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Swing Scanner V2 - Gelişmiş Sinyal Motoru</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    .table-sm th, .table-sm td { font-size: 0.85rem; }
    .strong-signal-row { background-color: #d1e7dd !important; } /* Yeşil */
    .bg-green-lite { background-color: #e6ffe6; } /* Trend & Momentum OK */
    .bg-red-lite { background-color: #f8d7da; }   /* Trend Uygun Değil */
    .bg-pullback-ok { background-color: #ccffcc; font-weight: bold; } /* Pullback OK */
    .bg-pullback-fail { background-color: #fff3cd; } /* Pullback Fail */
    .bg-zscore-high { font-weight: bold; background-color: #90ee90; } /* Yüksek Hacim Z-Score */
    .bg-reversal-ok { background-color: #b3e0ff; font-weight: bold; } /* Momentum Dönüşü */
    .tooltip-inner { max-width: 400px; } /* Tooltip genişliği */
  </style>
</head>
<body class="bg-light">
<div class="container-fluid mt-4">
  <h3 class="mb-3">🔥 Swing Scanner V2 - Gelişmiş Sinyal Motoru (Pullback & Reversal)</h3>
  <p class="text-muted">CSV: <code>{{ csv_name }}</code> | DB: <code>{{ db_name }}</code> | Cache: {{ cache_size }} Sembol</p>
  
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for cat, msg in messages %}
        <div class="alert alert-{{ cat }}">{{ msg | safe }}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  <div class="card mb-4 border-info">
      <div class="card-header bg-info text-white">⚙️ Risk ve Portföy Ayarları</div>
      <div class="card-body">
          <form method="post" action="{{ url_for('set_settings') }}" class="row g-3 align-items-center">
              <div class="col-auto">
                  <label for="portfolio_size" class="col-form-label">Portföy Büyüklüğü (TL)</label>
                  <input type="number" step="0.01" id="portfolio_size" name="portfolio_size" class="form-control" value="{{ portfolio_size }}" required>
              </div>
              <div class="col-auto">
                  <label for="risk_per_trade" class="col-form-label">Risk/İşlem (%)</label>
                  <input type="number" step="0.01" id="risk_per_trade" name="risk_per_trade" class="form-control" value="{{ (risk_per_trade * 100) | round(2) }}" required>
              </div>
              <div class="col-auto">
                  <button type="submit" class="btn btn-success mt-4">Ayarları Kaydet</button>
              </div>
              <div class="col-auto">
                  <small class="text-muted mt-4 d-block">Maksimum Risk Miktarı: **{{ (portfolio_size * risk_per_trade) | round(2) }} TL**</small>
              </div>
          </form>
      </div>
  </div>
  <div class="mb-3">
    <form method="post" action="{{ url_for('bootstrap') }}" onsubmit="return confirm('Bootstrap işlemi tüm semboller için tarihsel veriyi indirecek ve uzun sürebilir. Devam edilsin mi?');" class="d-inline me-2">
      <button class="btn btn-warning btn-sm">Tam Bootstrap (İlk Veri Yüklemesi)</button>
    </form>
    <form method="post" action="{{ url_for('update_all') }}" class="d-inline me-2">
      <button class="btn btn-secondary btn-sm">Güncelle (Son Eksik Günleri Çek)</button>
    </form>
    <form method="post" action="{{ url_for('scan') }}" class="d-inline me-2">
      <button class="btn btn-primary btn-sm">Tara ve Sinyalleri Göster</button>
    </form>
    
    {% if current_filter == 'strong' %}
      <a href="{{ url_for('scan') }}" class="btn btn-info btn-sm">Filtreyi Kaldır (Tümünü Göster)</a>
    {% endif %}
    
  </div>


  {% if results %}
    <div class="row mb-3">
        <div class="col-md-4">
            <div class="card border-primary">
                <div class="card-body">
                    <h5 class="card-title">Özet İstatistikler</h5>
                    <p class="card-text mb-1">Toplam Sembol: **{{ total_symbols }}**</p>
                    <p class="card-text">Güçlü Sinyal: <a href="{{ url_for('scan', filter='strong') }}" class="badge bg-success text-decoration-none">**{{ strong_signals }}**</a></p>
                    <p class="card-text"><small class="text-muted">Son Analiz Tarihi: **{{ analysis_date }}**</small></p>
                    <p class="card-text"><small class="text-muted">Risk Ayarı: %{{ (risk_per_trade * 100) | round(2) }} (Portföy: {{ portfolio_size | round(0) }} TL)</small></p>
                </div>
            </div>
        </div>
    </div>
    
    <table class="table table-sm table-bordered table-hover bg-white">
      <thead class="table-dark">
        <tr>
          <th><a href="{{ url_for_sort('symbol') }}" class="text-white text-decoration-none">Sembol</a></th>
          <th><a href="{{ url_for_sort('price') }}" class="text-white text-decoration-none">Fiyat</a></th>
          <th>MA20 (Eğim)</th><th>MA50</th><th>MA200</th>
          <th data-bs-toggle="tooltip" title="MA20'ye Geri Çekilme Aralığı (%2)" class="text-center">Pullback</th>
          <th data-bs-toggle="tooltip" title="Momentum Dönüşü (RSI < 55 & MACD Cross)" class="text-center">Reversal</th>
          <th>RSI</th><th>MACD Hist.</th>
          <th><a href="{{ url_for_sort('volume_zscore') }}" class="text-white text-decoration-none">Hacim Z-Score</a></th>
          <th data-bs-toggle="tooltip" title="Volatilite Oranı (%)">ATR%</th>
          <th data-bs-toggle="tooltip" title="SL Çarpanı: {{ dynamic_multiplier }}">Stop Loss</th>
          <th class="table-success">Önerilen Lot</th>
          <th>Sinyal Durumu</th>
          <th>Neden (Açıklama)</th>
        </tr>
      </thead>
      <tbody>
      {% for r in results %}
        <tr class="{% if r.is_strong_signal %}strong-signal-row{% elif r.status == 'Orta SWING SİNYALİ (Hacim Eksik)' %}table-info{% endif %}">
          <td>{{ r.symbol }}</td>
          {% if r.error %}
            <td colspan="12" class="text-danger">{{ r.error }}</td>
          {% else %}
            <td>{{ "%.2f" % r.price }}</td>
            <td class="{% if r.ma20_slope > 0 %}bg-green-lite{% else %}bg-red-lite{% endif %}">{{ "%.2f" % r.ma20 }}</td>
            <td class="{% if r.ma20 > r.ma50 %}bg-green-lite{% else %}bg-red-lite{% endif %}">{{ "%.2f" % r.ma50 }}</td>
            <td class="{% if r.ma50 > r.ma200 %}bg-green-lite{% else %}bg-red-lite{% endif %}">{{ "%.2f" % r.ma200 }}</td>
            
            {% set pullback_class = "bg-pullback-fail" %}
            {% if "Pullback: Fiyat, MA20 Destek Aralığında" in r.signal_reason %}
                {% set pullback_class = "bg-pullback-ok" %}
            {% endif %}
            <td class="{{ pullback_class }} text-center">
                {% if pullback_class == 'bg-pullback-ok' %} ✅ {% else %} ❌ {% endif %}
            </td>
            
            {% set reversal_class = "" %}
            {% if "Momentum: Dönüş sinyali yok" not in r.signal_reason %}
                {% set reversal_class = "bg-reversal-ok" %}
            {% endif %}
            <td class="{{ reversal_class }} text-center">
                {% if reversal_class == 'bg-reversal-ok' %} ✅ {% else %} ❌ {% endif %}
            </td>

            <td>{{ "%.2f" % r.rsi }}</td>
            <td>{{ "%.4f" % r.macd_hist }}</td>
            
            <td class="{% if r.volume_zscore >= volume_zscore_threshold %}bg-zscore-high{% endif %}">
                 {{ "%.2f" % r.volume_zscore }}
            </td>
            
            <td>{{ "%.2f" % r.atr_percent }}%</td>
            <td class="table-danger fw-bold" data-bs-toggle="tooltip" title="SL Çarpanı: {{ r.dynamic_multiplier | round(1) }}x">
                {{ "%.2f" % r.stop_loss if r.stop_loss is not none and r.stop_loss > 0 else 'N/A' }}
            </td>
            <td class="table-success fw-bold">{{ r.recommended_lot if r.recommended_lot is not none and r.recommended_lot > 0 else 'N/A' }}</td>
            
            <td class="fw-bold">{{ r.status }}</td>
            <td style="font-size: 0.75rem;">{{ r.signal_reason | replace("|", "<br>") | safe }}</td>
          {% endif %}
        </tr>
      {% endfor %}
      </tbody>
    </table>
  {% endif %}

  <hr>
  <p class="text-muted">
    **Pullback Sinyali:** Trend pozitifken fiyatın MA20'ye %1-3 yaklaşması.<br>
    **Dinamik Stop Loss:** ATR %2'nin altındaysa 2.5x, %5'in üstündeyse 1.0x çarpan kullanılır.
  </p>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    })
</script>
</body>
</html>
"""

@app.context_processor
def utility_processor():
    def url_for_sort(sort_by_column):
        current_sort_by = request.args.get('sort_by')
        current_sort_order = request.args.get('sort_order', 'desc')
        current_filter = request.args.get('filter')
        
        if current_sort_by == sort_by_column:
            new_sort_order = 'asc' if current_sort_order == 'desc' else 'desc'
        else:
            new_sort_order = 'desc'

        return url_for('scan', 
                       filter=current_filter, 
                       sort_by=sort_by_column, 
                       sort_order=new_sort_order)
    return dict(url_for_sort=url_for_sort)


@app.route("/", methods=["GET"])
def index():
    portfolio_size = session.get('portfolio_size', DEFAULT_PORTFOLIO_SIZE)
    risk_per_trade = session.get('risk_per_trade', DEFAULT_RISK_PER_TRADE)
    
    return render_template_string(TEMPLATE_INDEX, 
                                  csv_name=SYMBOLS_CSV, 
                                  db_name=DB_FILE, 
                                  results=None, 
                                  analysis_date="N/A", 
                                  total_symbols=len(load_symbols_from_csv()),
                                  strong_signals=0,
                                  current_filter=None,
                                  risk_per_trade=risk_per_trade,
                                  portfolio_size=portfolio_size,
                                  cache_size=len(DATA_CACHE),
                                  volume_zscore_threshold=VOLUME_ZSCORE_THRESHOLD)

@app.route("/set_settings", methods=["POST"])
def set_settings():
    try:
        portfolio_size = float(request.form.get('portfolio_size'))
        risk_percent = float(request.form.get('risk_per_trade'))
        
        if portfolio_size <= 0 or risk_percent <= 0:
            flash("Portföy büyüklüğü ve risk yüzdesi pozitif olmalıdır.", "danger")
            return redirect(url_for("index"))

        session['portfolio_size'] = portfolio_size
        session['risk_per_trade'] = risk_percent / 100.0 
        
        flash("Ayarlar başarıyla kaydedildi! Yeni tarama sonucunuz bu dinamik ayarlara göre güncellenecektir.", "success")
        return redirect(url_for("scan")) 
    except ValueError:
        flash("Geçersiz değerler girdiniz. Lütfen sayısal değerler kullanın.", "danger")
        return redirect(url_for("index"))

@app.route("/bootstrap", methods=["POST"])
def bootstrap():
    def job():
        cli_bootstrap_all() # CLI fonksiyonları artık yukarıda tanımlı
    threading.Thread(target=job).start()
    flash("Bootstrap başlatıldı (arka planda). Veri indirme tamamlandığında cache otomatik güncellenecektir.", "info")
    return redirect(url_for("index"))

@app.route("/update_all", methods=["POST"])
def update_all():
    def job():
        cli_update_all() # CLI fonksiyonları artık yukarıda tanımlı
    threading.Thread(target=job).start()
    flash("Tüm semboller için güncelleme başlatıldı (arka planda). Tamamlandığında cache otomatik güncellenecektir.", "info")
    return redirect(url_for("index"))

@app.route("/scan", methods=["POST", "GET"])
def scan():
    if not DATA_CACHE:
        flash("RAM Cache boş. Lütfen önce **Güncelle** veya **Bootstrap** yapın.", "warning")
        return redirect(url_for('index'))
        
    portfolio_size = session.get('portfolio_size', DEFAULT_PORTFOLIO_SIZE)
    risk_per_trade = session.get('risk_per_trade', DEFAULT_RISK_PER_TRADE)
    
    filter_param = request.args.get('filter')
    sort_by = request.args.get('sort_by')
    sort_order = request.args.get('sort_order', 'desc')
    
    syms = load_symbols_from_csv()
    all_results_for_count = []
    analysis_date = "N/A"
    strong_signals_count = 0
    total_count = len(syms)
    
    # POST ile gelindiyse (Tarama butonu tıklandıysa) güncelleme yap
    if request.method == 'POST':
        flash("Tarama başlamadan önce son güncellemeler kontrol ediliyor...", "secondary")
        for s in syms:
            ok, msg = update_symbol_prices(s)
            if not ok and "unique constraint" not in msg:
                logger.warning(f"Scan Update Error {s}: {msg}")
        load_all_data_to_cache() # Güncellemeler bitti, cache'i yeniden yükle
        
    # Analiz (Cache'ten çalışır, çok hızlıdır)
    for s in syms:
        try:
            status, vals = swing_signal_engine_v2(s, risk_per_trade, portfolio_size)
            
            if vals is None:
                all_results_for_count.append({"symbol": s, "error": status})
            else:
                result_entry = {
                    "symbol": vals["symbol"], 
                    "price": vals["price"], 
                    "ma20": vals["ma20"], 
                    "ma50": vals["ma50"], 
                    "ma200": vals["ma200"], 
                    "rsi": vals["rsi"], 
                    "macd_hist": vals["macd_hist"],
                    "volume_zscore": vals["volume_zscore"],
                    "ma20_slope": vals["ma20_slope"],
                    "atr": vals["atr"],
                    "atr_percent": vals["atr_percent"],
                    "dynamic_multiplier": vals["dynamic_multiplier"],
                    "stop_loss": vals["stop_loss"],
                    "recommended_lot": vals["recommended_lot"],
                    "status": status, 
                    "error": None,
                    "signal_reason": vals["signal_reason"],
                    "is_strong_signal": vals["is_strong_signal"]
                }
                analysis_date = vals["analysis_date"]
                
                if vals["is_strong_signal"]:
                    strong_signals_count += 1
            
                all_results_for_count.append(result_entry)
            
        except Exception as e:
            logger.error(f"Scan Error for {s}: {e}")
            all_results_for_count.append({"symbol": s, "error": f"Hesaplama Hatası: {e}"})

    # FİLTRELEME İŞLEMİ
    results = all_results_for_count
    if filter_param == 'strong':
        results = [r for r in all_results_for_count if r.get('is_strong_signal')]
    
    # SIRALAMA İŞLEMİ
    if sort_by:
        reverse = (sort_order == 'desc')
        
        sortable_results = [r for r in results if r.get(sort_by) is not None and r.get('error') is None]
        non_sortable_results = [r for r in results if r not in sortable_results]
        
        try:
            results = sorted(sortable_results, key=lambda x: x[sort_by], reverse=reverse)
            results.extend(non_sortable_results)
        except (KeyError, TypeError):
            results = all_results_for_count 

    
    return render_template_string(TEMPLATE_INDEX, 
                                  csv_name=SYMBOLS_CSV, 
                                  db_name=DB_FILE, 
                                  results=results, 
                                  analysis_date=analysis_date,
                                  total_symbols=total_count,
                                  strong_signals=strong_signals_count,
                                  current_filter=filter_param,
                                  risk_per_trade=risk_per_trade,
                                  portfolio_size=portfolio_size,
                                  cache_size=len(DATA_CACHE),
                                  volume_zscore_threshold=VOLUME_ZSCORE_THRESHOLD)

# ---------- main ----------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true", help="Tüm semboller için bootstrap (tüm tarihleri indir).")
    parser.add_argument("--update", action="store_true", help="CSV'deki tüm semboller için cache güncelle.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()

    init_db()
    load_all_data_to_cache() # Uygulama başlarken cache'i doldur

    if args.bootstrap:
        cli_bootstrap_all()
        raise SystemExit(0)
    if args.update:
        cli_update_all()
        raise SystemExit(0)
        
    app.run(host=args.host, port=args.port, debug=True, use_reloader=False)