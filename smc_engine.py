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
        """Single consolidated data fetch to conserve Twelve Data API credits."""
        if not self.api_key:
            return pd.DataFrame()

        url = f"https://api.twelvedata.com/time_series?symbol={self.symbol}&interval={interval}&outputsize={outputsize}&apikey={self.api_key}"
        try:
            res = requests.get(url, timeout=10)
            data = res.json()
            if "values" not in data:
                print(f"[Twelve Data Warning]: {data.get('message', 'No values')}")
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
            print(f"[XAUUSD Fetch Error]: {e}")
            return pd.DataFrame()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

        # ATR (14)
        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14).mean()

        # RSI (14)
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        df["RSI"] = 100 - (100 / (1 + rs))
        return df

    def scan_for_setups(self, macro_report: dict) -> dict:
        """High-Probability Trend Continuation with ATR Volatility Filter."""
        df = self.fetch_data(interval="15min", outputsize=80)
        if df.empty or len(df) < 50:
            return {"status": "NO_DATA", "candle": None}

        df = self.calculate_indicators(df)
        curr = df.iloc[-1]
        prior = df.iloc[-2]
        macro_score = macro_report.get("macro_score", 0)

        atr = round(curr["ATR"], 2) if not np.isnan(curr["ATR"]) else 4.5
        curr_price = round(curr["Close"], 2)

        # High-probability volatility gate: reject low-volume consolidations
        atr_active = atr >= 2.5
        setup = None

        # --- BEARISH HIGH-CONVICTION SETUP ---
        # Requirements: Macro strongly negative, EMAs strictly aligned down, Pullback rejection, RSI < 48
        if macro_score <= -2.5 and atr_active:
            trend_down = curr["Close"] < curr["EMA50"] and curr["EMA20"] < curr["EMA50"]
            pullback = prior["High"] >= curr["EMA20"] - 0.50
            rejection = curr["Close"] < curr["Open"] and curr["Close"] < curr["EMA20"]
            rsi_bear = curr["RSI"] < 48.0

            if trend_down and pullback and rejection and rsi_bear:
                sl_distance = max(round(atr * 1.5, 2), 4.5)
                sl_price = round(curr_price + sl_distance, 2)
                tp1 = round(curr_price - (sl_distance * 1.5), 2)
                tp2 = round(curr_price - (sl_distance * 2.5), 2)

                setup = {
                    "signal": "SELL MARKET",
                    "direction": "BEARISH",
                    "reason": f"15m Trend Pullback + Macro Alignment ({macro_score}/5) + Volatility Expansion",
                    "entry_zone": f"${curr_price}",
                    "stop_loss": sl_price,
                    "tp1": tp1,
                    "tp2": tp2,
                    "risk_reward": "1:2.5",
                    "atr": atr
                }

        # --- BULLISH HIGH-CONVICTION SETUP ---
        elif macro_score >= 2.5 and atr_active:
            trend_up = curr["Close"] > curr["EMA50"] and curr["EMA20"] > curr["EMA50"]
            pullback = prior["Low"] <= curr["EMA20"] + 0.50
            bounce = curr["Close"] > curr["Open"] and curr["Close"] > curr["EMA20"]
            rsi_bull = curr["RSI"] > 52.0

            if trend_up and pullback and bounce and rsi_bull:
                sl_distance = max(round(atr * 1.5, 2), 4.5)
                sl_price = round(curr_price - sl_distance, 2)
                tp1 = round(curr_price + (sl_distance * 1.5), 2)
                tp2 = round(curr_price + (sl_distance * 2.5), 2)

                setup = {
                    "signal": "BUY MARKET",
                    "direction": "BULLISH",
                    "reason": f"15m Trend Pullback + Macro Alignment (+{macro_score}/5) + Volatility Expansion",
                    "entry_zone": f"${curr_price}",
                    "stop_loss": sl_price,
                    "tp1": tp1,
                    "tp2": tp2,
                    "risk_reward": "1:2.5",
                    "atr": atr
                }

        latest_candle = {"High": float(curr["High"]), "Low": float(curr["Low"])}
        return {
            "status": "READY",
            "levels": {"current_price": curr_price, "asian_high": round(df["High"].iloc[-30:].max(), 2), "asian_low": round(df["Low"].iloc[-30:].min(), 2)},
            "active_setup": setup,
            "candle": latest_candle
        }
