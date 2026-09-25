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
            print(f"[XAUUSD Fetch Error]: {e}")
            return pd.DataFrame()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14).mean()

        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        df["RSI"] = 100 - (100 / (1 + rs))
        return df

    def get_session_liquidity(self, df: pd.DataFrame) -> dict:
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        asian_df = df[(df.index.date == today) & (df.index.hour >= 0) & (df.index.hour < 6)]
        if not asian_df.empty:
            asian_high = round(asian_df['High'].max(), 2)
            asian_low = round(asian_df['Low'].min(), 2)
        else:
            asian_high = round(df['High'].iloc[-24:].max(), 2)
            asian_low = round(df['Low'].iloc[-24:].min(), 2)

        yesterday_df = df[df.index.date < today]
        if not yesterday_df.empty:
            last_date = yesterday_df.index.date.max()
            last_candles = yesterday_df[yesterday_df.index.date == last_date]
            pdh = round(last_candles['High'].max(), 2)
            pdl = round(last_candles['Low'].min(), 2)
        else:
            pdh, pdl = asian_high, asian_low

        curr_price = round(df['Close'].iloc[-1], 2)
        return {
            "current_price": curr_price,
            "asian_high": asian_high,
            "asian_low": asian_low,
            "pdh": pdh,
            "pdl": pdl
        }

    def scan_for_setups(self, macro_report: dict) -> dict:
        df = self.fetch_data(interval="15min", outputsize=80)
        if df.empty or len(df) < 50:
            return {"status": "NO_DATA", "candle": None}

        df = self.calculate_indicators(df)
        curr = df.iloc[-1]
        prior = df.iloc[-2]
        macro_score = macro_report.get("macro_score", 0)

        atr = round(curr["ATR"], 2) if not np.isnan(curr["ATR"]) else 4.5
        levels = self.get_session_liquidity(df)
        curr_price = levels["current_price"]
        setup = None

        # Threshold calibrated to 1.5 for active trend participation
        if macro_score <= -1.5 and atr >= 2.0:
            trend_down = curr["Close"] < curr["EMA50"] and curr["EMA20"] < curr["EMA50"]
            pullback = prior["High"] >= curr["EMA20"] - 0.75
            rejection = curr["Close"] < curr["Open"] and curr["Close"] < curr["EMA20"]
            rsi_bear = curr["RSI"] < 50.0

            if trend_down and pullback and rejection and rsi_bear:
                sl_distance = max(round(atr * 1.5, 2), 4.5)
                sl_price = round(curr_price + sl_distance, 2)
                tp1 = round(curr_price - (sl_distance * 1.5), 2)
                tp2 = round(curr_price - (sl_distance * 2.5), 2)

                setup = {
                    "signal": "SELL MARKET",
                    "direction": "BEARISH",
                    "reason": f"15m Trend Pullback + Macro Alignment ({macro_score}/5)",
                    "entry_zone": f"${curr_price}",
                    "stop_loss": sl_price,
                    "tp1": tp1,
                    "tp2": tp2,
                    "risk_reward": "1:2.5",
                    "atr": atr
                }

        elif macro_score >= 1.5 and atr >= 2.0:
            trend_up = curr["Close"] > curr["EMA50"] and curr["EMA20"] > curr["EMA50"]
            pullback = prior["Low"] <= curr["EMA20"] + 0.75
            bounce = curr["Close"] > curr["Open"] and curr["Close"] > curr["EMA20"]
            rsi_bull = curr["RSI"] > 50.0

            if trend_up and pullback and bounce and rsi_bull:
                sl_distance = max(round(atr * 1.5, 2), 4.5)
                sl_price = round(curr_price - sl_distance, 2)
                tp1 = round(curr_price + (sl_distance * 1.5), 2)
                tp2 = round(curr_price + (sl_distance * 2.5), 2)

                setup = {
                    "signal": "BUY MARKET",
                    "direction": "BULLISH",
                    "reason": f"15m Trend Pullback + Macro Alignment (+{macro_score}/5)",
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
            "levels": levels,
            "active_setup": setup,
            "candle": latest_candle
        }
