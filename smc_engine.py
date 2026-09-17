import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

class SMCEngine:
    def __init__(self, symbol="XAU/USD"):
        self.symbol = symbol
        self.api_key = TWELVE_DATA_API_KEY

    def fetch_data(self, interval="15min", outputsize=100) -> pd.DataFrame:
        """Fetches 15-minute candles for clean trend momentum."""
        if not self.api_key:
            return pd.DataFrame()

        url = f"https://api.twelvedata.com/time_series?symbol={self.symbol}&interval={interval}&outputsize={outputsize}&apikey={self.api_key}"
        try:
            res = requests.get(url, timeout=10)
            data = res.json()
            if "values" not in data:
                return pd.DataFrame()

            df = pd.DataFrame(data["values"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            df.set_index("datetime", inplace=True)
            df = df.sort_index()

            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype(float)

            df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"}, inplace=True)
            return df
        except Exception as e:
            print(f"[Fetch Error]: {e}")
            return pd.DataFrame()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculates 20 EMA, 50 EMA, ATR(14), and RSI(14)."""
        # EMAs
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

        # ATR (Average True Range)
        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["ATR"] = true_range.rolling(14).mean()

        # RSI (14)
        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        df["RSI"] = 100 - (100 / (1 + rs))
        return df

    def get_session_liquidity(self, df: pd.DataFrame) -> dict:
        curr_price = round(df['Close'].iloc[-1], 2)
        pdh = round(df['High'].iloc[-30:].max(), 2)
        pdl = round(df['Low'].iloc[-30:].min(), 2)
        return {"current_price": curr_price, "asian_high": pdh, "asian_low": pdl, "pdh": pdh, "pdl": pdl}

    def scan_for_setups(self, macro_report: dict) -> dict:
        """Executes Trend-Continuation Pullback Strategy aligned with Macro."""
        df = self.fetch_data(interval="15min", outputsize=80)
        if df.empty or len(df) < 50:
            return {"status": "NO_DATA"}

        df = self.calculate_indicators(df)
        curr = df.iloc[-1]
        prior = df.iloc[-2]
        macro_score = macro_report.get("macro_score", 0)

        atr = round(curr["ATR"], 2) if not np.isnan(curr["ATR"]) else 4.0
        levels = self.get_session_liquidity(df)
        setup = None

        # ---------------- BEARISH TREND CONTINUATION (SHORTS) ----------------
        # 1. Macro is Bearish
        # 2. Trend: Price below both 20 & 50 EMA, 20 EMA < 50 EMA
        # 3. Pullback: Prior candle touched the 20/50 EMA value zone
        # 4. Confirmation: Current candle closes red below 20 EMA & RSI < 50
        if macro_score <= -1:
            trend_down = curr["Close"] < curr["EMA50"] and curr["EMA20"] < curr["EMA50"]
            pullback_tested = prior["High"] >= curr["EMA20"]
            bearish_rejection = curr["Close"] < curr["Open"] and curr["Close"] < curr["EMA20"]
            momentum_down = curr["RSI"] < 50

            if trend_down and pullback_tested and bearish_rejection and momentum_down:
                entry = round(curr["Close"], 2)
                sl_distance = max(round(atr * 1.5, 2), 4.0)  # Safe buffer
                sl_price = round(entry + sl_distance, 2)
                tp1 = round(entry - (sl_distance * 1.5), 2)
                tp2 = round(entry - (sl_distance * 2.5), 2)

                setup = {
                    "signal": "SELL MARKET",
                    "direction": "BEARISH",
                    "reason": "15m Macro Trend Pullback into EMA Value Zone + Bearish Rejection",
                    "entry_zone": f"${entry}",
                    "stop_loss": sl_price,
                    "tp1": tp1,
                    "tp2": tp2,
                    "risk_reward": "1:2.5",
                    "atr": atr
                }

        # ---------------- BULLISH TREND CONTINUATION (LONGS) ----------------
        elif macro_score >= 1:
            trend_up = curr["Close"] > curr["EMA50"] and curr["EMA20"] > curr["EMA50"]
            pullback_tested = prior["Low"] <= curr["EMA20"]
            bullish_bounce = curr["Close"] > curr["Open"] and curr["Close"] > curr["EMA20"]
            momentum_up = curr["RSI"] > 50

            if trend_up and pullback_tested and bullish_bounce and momentum_up:
                entry = round(curr["Close"], 2)
                sl_distance = max(round(atr * 1.5, 2), 4.0)
                sl_price = round(entry - sl_distance, 2)
                tp1 = round(entry + (sl_distance * 1.5), 2)
                tp2 = round(entry + (sl_distance * 2.5), 2)

                setup = {
                    "signal": "BUY MARKET",
                    "direction": "BULLISH",
                    "reason": "15m Macro Trend Pullback into EMA Value Zone + Bullish Rejection",
                    "entry_zone": f"${entry}",
                    "stop_loss": sl_price,
                    "tp1": tp1,
                    "tp2": tp2,
                    "risk_reward": "1:2.5",
                    "atr": atr
                }

        return {
            "status": "READY",
            "levels": levels,
            "active_setup": setup,
            "fvgs": []
        }
