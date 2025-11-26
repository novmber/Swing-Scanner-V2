# indicators_v2.py

import pandas as pd
import numpy as np

# Tüm gösterge hesaplama fonksiyonları

def calculate_rsi(df, window=14):
    """Relative Strength Index (RSI) hesaplar."""
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(com=window - 1, min_periods=window).mean()
    avg_loss = loss.ewm(com=window - 1, min_periods=window).mean()
    rs = avg_gain / avg_loss
    # Sıfır bölmeyi önlemek için np.inf kontrolü
    rs.replace([np.inf, -np.inf], np.nan, inplace=True) 
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def calculate_macd(df, fast=12, slow=26, signal=9):
    """Moving Average Convergence Divergence (MACD) hesaplar."""
    df['ema_fast'] = df['close'].ewm(span=fast, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow, adjust=False).mean()
    df['macd'] = df['ema_fast'] - df['ema_slow']
    df['macd_signal_line'] = df['macd'].ewm(span=signal, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal_line']
    return df

def calculate_atr(df, window=14):
    """Average True Range (ATR) hesaplar."""
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift(1))
    low_close = np.abs(df['low'] - df['close'].shift(1))
    df['tr'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = df['tr'].ewm(span=window, adjust=False, min_periods=window).mean()
    
    # ATR Yüzdesi (Volatilitenin fiyata oranı)
    df['atr_percent'] = (df['atr'] / df['close']) * 100
    
    return df

def calculate_volume_zscore(df, window=20):
    """Hacimdeki sapmayı (Z-Score) hesaplar."""
    df['volume_ma'] = df['volume'].rolling(window=window).mean()
    df['volume_std'] = df['volume'].rolling(window=window).std()
    
    # Z-Score: (Güncel Hacim - Hacim Ortalaması) / Hacim Standart Sapması
    # Sıfır bölme hatalarını ve NaN'ları yönetir
    df['volume_zscore'] = (df['volume'] - df['volume_ma']) / df['volume_std']
    df.loc[df['volume_std'] == 0, 'volume_zscore'] = 0
    df['volume_zscore'].fillna(0, inplace=True)
    
    return df

def calculate_ma_slope(df, ma_period=20, slope_period=5):
    """MA'nın eğimini (son 5 günlük değişim) hesaplar. ma20_slope sütununu ekler."""
    ma_col = f'ma{ma_period}'
    slope_col = f'ma{ma_period}_slope'
    
    # ma20'nin 5 gün önceki değeri ile bugünkü değeri arasındaki farkı hesapla
    df[slope_col] = df[ma_col] - df[ma_col].shift(slope_period)
    
    return df