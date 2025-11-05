import os
import time

import numpy as np
import pandas as pd
import yfinance as yf
import threading

from vars import *

def _get_from_container(container, keys):
    if container is None:
        return None
    for k in keys:
        v = None
        # dict 스타일
        try:
            v = container.get(k, None)
        except Exception:
            pass
        # attr 스타일
        if v is None:
            try:
                v = getattr(container, k)
            except Exception:
                v = None
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    return None

def get_current_price_any(ticker: str) -> float:
    t = yf.Ticker(ticker)

    try:
        fi = t.fast_info
        price = _get_from_container(fi, [
            "last_price", "lastPrice",
            "regular_market_price", "regularMarketPrice",
            "last_traded_price", "lastTradedPrice",
            "previous_close", "previousClose"
        ])
        if price and price > 0:
            return price
    except Exception:
        pass

    try:
        info = t.info or {}
        price = _get_from_container(info, [
            "currentPrice",
            "regularMarketPrice",
            "regularMarketPreviousClose",
            "previousClose",
            "navPrice",
        ])
        if price and price > 0:
            return price
    except Exception:
        pass

    for period, interval in [("1d", "1m"), ("5d", "5m")]:
        try:
            h = t.history(period=period, interval=interval, auto_adjust=False)
            if not h.empty and "Close" in h:
                last = h["Close"].dropna().iloc[-1]
                if pd.notna(last) and last > 0:
                    return float(last)
        except Exception:
            continue

    try:
        h = t.history(period="1mo", interval="1d", auto_adjust=False)
        if not h.empty and "Close" in h:
            last = h["Close"].dropna().iloc[-1]
            if pd.notna(last) and last > 0:
                return float(last)
    except Exception:
        pass

    raise RuntimeError(f"[{ticker}] 현재가를 판별할 수 없습니다.")

_history_cache: dict[tuple[str, bool], dict] = {}
_cache_lock = threading.Lock()

def get_history_df(ticker: str, adjusted: bool) -> pd.DataFrame:
    key = (ticker, bool(adjusted))
    now = time.time()
    with _cache_lock:
        cached = _history_cache.get(key)
        if cached and now - cached["ts"] < HISTORY_TTL_SEC:
            return cached["df"]

    df = yf.Ticker(ticker).history(period="max", interval="1d", auto_adjust=adjusted)
    if df is None or df.empty:
        raise RuntimeError(f"[{ticker}] 일봉 데이터가 비어 있음.")

    with _cache_lock:
        _history_cache[key] = {"df": df, "ts": now}
    return df

def read_tickers_from_file(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    tickers = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#"):
                continue
            tickers.append(s)
    # 중복 제거, 순서 보존
    uniq, seen = [], set()
    for t in tickers:
        if t not in seen:
            uniq.append(t)
            seen.add(t)
    return uniq

def compute_metrics_for_ticker(ticker: str) -> dict:
    current_price = float(get_current_price_any(ticker))

    df_raw = get_history_df(ticker, adjusted=False)
    if "High" not in df_raw.columns:
        raise RuntimeError(f"[{ticker}] High 컬럼 없음.")
    historical_max = float(df_raw["High"].max())

    current_draw_down = ((current_price - historical_max) / historical_max) * 100.0

    series = df_raw[["High"]].copy()
    series["PeakToDate"] = series["High"].cummax()
    series["DrawdownPct_PeakToDate"] = (series["High"] / series["PeakToDate"] - 1.0) * 100.0

    row_count = len(series)
    if row_count == 0:
        recover_ratio = np.nan
    else:
        mask = series["DrawdownPct_PeakToDate"] > current_draw_down
        true_count = int(mask.sum())
        recover_ratio = (true_count / row_count) * 100.0

    return {
        "ticker": ticker,
        "current_price": round(current_price, ROUND_DIGITS),
        "historical_max": round(historical_max, ROUND_DIGITS),
        "current_draw_down_pct": round(current_draw_down, ROUND_DIGITS),
        "recover_ratio": round(recover_ratio, ROUND_DIGITS) if pd.notna(recover_ratio) else np.nan,
        "error": "",
        "_cur_raw": float(current_price),
        "_hist_raw": float(historical_max),
        "_dd_raw": float(current_draw_down),
        "_rr_raw": float(recover_ratio) if pd.notna(recover_ratio) else float("nan"),
    }