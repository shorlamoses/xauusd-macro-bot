import os
import requests
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv

# Load credentials from .env
load_dotenv()
FRED_API_KEY = os.getenv("FRED_API_KEY")

class MacroCompass:
    def __init__(self):
        self.dxy_symbol = "DX-Y.NYB"   # US Dollar Index
        self.us10y_symbol = "^TNX"     # US 10-Year Treasury Yield

    def get_dxy_momentum(self) -> dict:
        """
        Analyzes DXY 1-hour and daily momentum.
        Returns trend direction and score component (-2 to +2 for Gold).
        """
        try:
            dxy = yf.Ticker(self.dxy_symbol)
            # Pull intraday 1-hour data for the last 5 days
            df = dxy.history(period="5d", interval="1h")
            if df.empty:
                return {"trend": "UNKNOWN", "score": 0, "price": 0.0}

            current_price = df["Close"].iloc[-1]
            ema_20 = df["Close"].ewm(span=20, adjust=False).mean().iloc[-1]
            prior_close = df["Close"].iloc[-5] # 5 hours ago

            # Inverse correlation: Falling DXY is Bullish for Gold
            if current_price < ema_20 and current_price < prior_close:
                return {"trend": "BEARISH (Falling)", "score": 2, "price": round(current_price, 2)}
            elif current_price > ema_20 and current_price > prior_close:
                return {"trend": "BULLISH (Rising)", "score": -2, "price": round(current_price, 2)}
            else:
                return {"trend": "NEUTRAL / RANGING", "score": 0, "price": round(current_price, 2)}
        except Exception as e:
            print(f"[Error fetching DXY]: {e}")
            return {"trend": "ERROR", "score": 0, "price": 0.0}

    def get_us10y_momentum(self) -> dict:
        """
        Analyzes US 10-Year Treasury Yield momentum.
        Returns trend direction and score component (-2 to +2 for Gold).
        """
        try:
            tnx = yf.Ticker(self.us10y_symbol)
            df = tnx.history(period="5d", interval="1h")
            if df.empty:
                return {"trend": "UNKNOWN", "score": 0, "yield": 0.0}

            current_yield = df["Close"].iloc[-1]
            ema_20 = df["Close"].ewm(span=20, adjust=False).mean().iloc[-1]
            prior_yield = df["Close"].iloc[-5]

            # Inverse correlation: Falling yields eliminate opportunity cost for holding Gold
            if current_yield < ema_20 and current_yield < prior_yield:
                return {"trend": "BEARISH (Falling)", "score": 2, "yield": round(current_yield, 2)}
            elif current_yield > ema_20 and current_yield > prior_yield:
                return {"trend": "BULLISH (Rising)", "score": -2, "yield": round(current_yield, 2)}
            else:
                return {"trend": "NEUTRAL / RANGING", "score": 0, "yield": round(current_yield, 2)}
        except Exception as e:
            print(f"[Error fetching US10Y]: {e}")
            return {"trend": "ERROR", "score": 0, "yield": 0.0}

    def get_real_yield_trend(self) -> dict:
        """
        Fetches 10-Year TIPS Real Yield from FRED (Series: DFII10).
        """
        if not FRED_API_KEY:
            return {"trend": "NO_API_KEY", "score": 0, "rate": None}

        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=5"
        try:
            res = requests.get(url, timeout=10)
            data = res.json()
            observations = data.get("observations", [])

            # Filter out holidays/missing data '.'
            valid_rates = [float(obs["value"]) for obs in observations if obs["value"] != "."]

            if len(valid_rates) >= 2:
                latest = valid_rates[0]
                previous = valid_rates[1]
                # If Real Yields are falling, it is bullish for Gold
                if latest < previous:
                    return {"trend": "FALLING", "score": 1, "rate": latest}
                elif latest > previous:
                    return {"trend": "RISING", "score": -1, "rate": latest}
                else:
                    return {"trend": "FLAT", "score": 0, "rate": latest}
            return {"trend": "INSUFFICIENT_DATA", "score": 0, "rate": None}
        except Exception as e:
            print(f"[Error fetching Real Yield from FRED]: {e}")
            return {"trend": "ERROR", "score": 0, "rate": None}

    def calculate_macro_bias(self) -> dict:
        """
        Aggregates all components into a definitive Gold Macro Score (-5 to +5).
        """
        dxy_data = self.get_dxy_momentum()
        yield_data = self.get_us10y_momentum()
        real_yield_data = self.get_real_yield_trend()

        total_score = dxy_data["score"] + yield_data["score"] + real_yield_data["score"]

        # Interpret the score
        if total_score >= 3:
            bias = "STRONG BULLISH"
            action = "LOOK FOR LONGS ONLY (Liquidity Sweeps of Lows)"
        elif total_score in [1, 2]:
            bias = "MILD BULLISH"
            action = "BULLISH BIAS (Exercise caution around resistance)"
        elif total_score == 0:
            bias = "NEUTRAL / CONFLICTED"
            action = "WAIT / TRADE STRICTLY SESSION RANGES"
        elif total_score in [-1, -2]:
            bias = "MILD BEARISH"
            action = "BEARISH BIAS (Exercise caution around support)"
        else:
            bias = "STRONG BEARISH"
            action = "LOOK FOR SHORTS ONLY (Liquidity Sweeps of Highs)"

        return {
            "macro_score": total_score,
            "macro_bias": bias,
            "trading_directive": action,
            "dxy": dxy_data,
            "us10y": yield_data,
            "real_yield_tips": real_yield_data
        }

if __name__ == "__main__":
    print("\n--- Scanning Intermarket Drivers for XAUUSD ---")
    compass = MacroCompass()
    report = compass.calculate_macro_bias()
    
    print(f"\n================ MACRO REPORT ================")
    print(f"Overall Macro Bias: {report['macro_bias']} (Score: {report['macro_score']}/5)")
    print(f"Directive:          {report['trading_directive']}")
    print(f"----------------------------------------------")
    print(f"DXY (USD Index):    {report['dxy']['price']} | Trend: {report['dxy']['trend']}")
    print(f"US10Y Yield:        {report['us10y']['yield']}% | Trend: {report['us10y']['trend']}")
    print(f"10Y TIPS Real Rate: {report['real_yield_tips']['rate']}% | Trend: {report['real_yield_tips']['trend']}")
    print(f"==============================================\n")