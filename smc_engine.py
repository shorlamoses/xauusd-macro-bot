import os
import requests
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

class SMCEngine:
    def __init__(self, symbol="XAU/USD"):
        self.symbol = symbol
        self.api_key = TWELVE_DATA_API_KEY

    def fetch_data(self, interval="5min", outputsize=100) -> pd.DataFrame:
        """Fetches live Spot Gold (XAU/USD) candle data from Twelve Data."""
        if not self.api_key:
            print("[Error]: Missing TWELVE_DATA_API_KEY in .env")
            return pd.DataFrame()

        url = f"https://api.twelvedata.com/time_series?symbol={self.symbol}&interval={interval}&outputsize={outputsize}&apikey={self.api_key}"
        
        try:
            res = requests.get(url, timeout=10)
            data = res.json()

            if "values" not in data:
                print(f"[Twelve Data Error]: {data.get('message', 'No candle values found')}")
                return pd.DataFrame()

            # Parse candles into DataFrame
            df = pd.DataFrame(data["values"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            df.set_index("datetime", inplace=True)
            
            # Sort ascending (oldest first)
            df = df.sort_index()

            # Convert price columns to floats
            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype(float)

            # Standardize column names (Capitalized)
            df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"}, inplace=True)
            return df
        except Exception as e:
            print(f"[Data Fetch Exception]: {e}")
            return pd.DataFrame()

    def get_session_liquidity(self, df: pd.DataFrame) -> dict:
        """Calculates Asian Range (00:00-06:00 UTC) & Previous Day High/Low."""
        if df.empty:
            return {}

        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        # Asian Session (00:00 to 06:00 UTC)
        asian_df = df[(df.index.date == today) & (df.index.hour >= 0) & (df.index.hour < 6)]
        
        if not asian_df.empty:
            asian_high = round(asian_df['High'].max(), 2)
            asian_low = round(asian_df['Low'].min(), 2)
        else:
            asian_high = round(df['High'].iloc[-24:].max(), 2)
            asian_low = round(df['Low'].iloc[-24:].min(), 2)

        # Previous Day High / Low
        yesterday_df = df[df.index.date < today]
        if not yesterday_df.empty:
            last_date = yesterday_df.index.date.max()
            last_day_candles = yesterday_df[yesterday_df.index.date == last_date]
            pdh = round(last_day_candles['High'].max(), 2)
            pdl = round(last_day_candles['Low'].min(), 2)
        else:
            pdh = round(df['High'].max(), 2)
            pdl = round(df['Low'].min(), 2)

        current_price = round(df['Close'].iloc[-1], 2)

        return {
            "current_price": current_price,
            "asian_high": asian_high,
            "asian_low": asian_low,
            "pdh": pdh,
            "pdl": pdl
        }

    def detect_fvg(self, df: pd.DataFrame) -> list:
        """Detects active 3-candle Fair Value Gaps (FVG)."""
        fvgs = []
        if len(df) < 5:
            return fvgs

        for i in range(len(df) - 15, len(df) - 1):
            c1 = df.iloc[i - 2]
            c2 = df.iloc[i - 1]
            c3 = df.iloc[i]

            # Bullish FVG
            if c1['High'] < c3['Low']:
                gap_top = round(c3['Low'], 2)
                gap_bottom = round(c1['High'], 2)
                subsequent_lows = df['Low'].iloc[i+1:].min() if i + 1 < len(df) else 999999
                if subsequent_lows > gap_bottom:
                    fvgs.append({
                        "type": "BULLISH_FVG",
                        "top": gap_top,
                        "bottom": gap_bottom,
                        "time": df.index[i].strftime("%H:%M")
                    })

            # Bearish FVG
            elif c1['Low'] > c3['High']:
                gap_top = round(c1['Low'], 2)
                gap_bottom = round(c3['High'], 2)
                subsequent_highs = df['High'].iloc[i+1:].max() if i + 1 < len(df) else 0
                if subsequent_highs < gap_top:
                    fvgs.append({
                        "type": "BEARISH_FVG",
                        "top": gap_top,
                        "bottom": gap_bottom,
                        "time": df.index[i].strftime("%H:%M")
                    })
        return fvgs

    def scan_for_setups(self, macro_report: dict) -> dict:
        """Evaluates Macro + Liquidity Sweeps + FVGs."""
        df = self.fetch_data(interval="5min", outputsize=80)
        if df.empty:
            return {"status": "NO_DATA"}

        levels = self.get_session_liquidity(df)
        fvgs = self.detect_fvg(df)
        macro_score = macro_report.get("macro_score", 0)
        curr_price = levels["current_price"]

        # Check last 8 candles (past 40 minutes) for sweeps
        recent = df.iloc[-8:]
        high_sweep = recent['High'].max() > levels['asian_high'] and curr_price < levels['asian_high']
        low_sweep = recent['Low'].min() < levels['asian_low'] and curr_price > levels['asian_low']

        setup = None

        # ---------------- BEARISH SETUP ----------------
        if macro_score <= 0 and high_sweep:
            bearish_fvgs = [f for f in fvgs if f["type"] == "BEARISH_FVG"]
            entry_top = bearish_fvgs[-1]["top"] if bearish_fvgs else curr_price + 1.00
            entry_bottom = bearish_fvgs[-1]["bottom"] if bearish_fvgs else curr_price + 0.30
            sl_price = round(recent['High'].max() + 1.20, 2)
            risk = round(abs(entry_top - sl_price), 2)
            tp1 = round(entry_bottom - (risk * 2), 2)
            tp2 = levels['asian_low']

            setup = {
                "signal": "SELL LIMIT",
                "direction": "BEARISH",
                "reason": "Asian High Liquidity Swept + Macro Bearish Alignment",
                "entry_zone": f"${entry_bottom} - ${entry_top}",
                "stop_loss": sl_price,
                "tp1": tp1,
                "tp2": tp2,
                "risk_reward": f"1:{round(abs(entry_bottom - tp2) / (risk or 1), 1)}",
                "fvg_detected": bool(bearish_fvgs)
            }

        # ---------------- BULLISH SETUP ----------------
        elif macro_score >= 0 and low_sweep:
            bullish_fvgs = [f for f in fvgs if f["type"] == "BULLISH_FVG"]
            entry_top = bullish_fvgs[-1]["top"] if bullish_fvgs else curr_price - 0.30
            entry_bottom = bullish_fvgs[-1]["bottom"] if bullish_fvgs else curr_price - 1.00
            sl_price = round(recent['Low'].min() - 1.20, 2)
            risk = round(abs(sl_price - entry_bottom), 2)
            tp1 = round(entry_top + (risk * 2), 2)
            tp2 = levels['asian_high']

            setup = {
                "signal": "BUY LIMIT",
                "direction": "BULLISH",
                "reason": "Asian Low Liquidity Swept + Macro Bullish Alignment",
                "entry_zone": f"${entry_bottom} - ${entry_top}",
                "stop_loss": sl_price,
                "tp1": tp1,
                "tp2": tp2,
                "risk_reward": f"1:{round(abs(tp2 - entry_top) / (risk or 1), 1)}",
                "fvg_detected": bool(bullish_fvgs)
            }

        return {
            "status": "READY",
            "levels": levels,
            "active_setup": setup,
            "fvgs": fvgs[-3:] if fvgs else []
        }

if __name__ == "__main__":
    from macro_engine import MacroCompass

    print("\n--- Connecting to Twelve Data Institutional Spot Feed ---")
    compass = MacroCompass()
    macro_rep = compass.calculate_macro_bias()

    smc = SMCEngine()
    result = smc.scan_for_setups(macro_rep)

    if result["status"] == "READY":
        print("\n================ LIVE SPOT SMC STATUS ================")
        print(f"Current Spot Gold Price: ${result['levels']['current_price']}")
        print(f"Asian Range:             ${result['levels']['asian_low']}  <--->  ${result['levels']['asian_high']}")
        print(f"Previous Day Range:      ${result['levels']['pdl']}  <--->  ${result['levels']['pdh']}")
        print(f"Active FVGs Detected:    {len(result['fvgs'])}")
        print("------------------------------------------------------")
        
        if result["active_setup"]:
            s = result["active_setup"]
            print(f"🚨 ACTIVE SETUP: {s['signal']}")
            print(f"Entry Zone:     {s['entry_zone']}")
            print(f"Stop Loss:      ${s['stop_loss']}")
            print(f"Target 1:       ${s['tp1']}")
            print(f"Target 2:       ${s['tp2']}")
        else:
            print("⏳ STATUS: SCANNING (No active liquidity sweep right now).")
            print(f"Monitoring Asian High (${result['levels']['asian_high']}) & Asian Low (${result['levels']['asian_low']}).")
        print("======================================================\n")