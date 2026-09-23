import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from dotenv import load_dotenv

from macro_engine import MacroCompass
from smc_engine import SMCEngine
from telegram_notifier import TelegramNotifier

load_dotenv()

# --- HEALTH SERVER FOR RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"XAUUSD_SENTINEL_OK_200")

    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# --- GOLD SENTINEL WITH TRADE TRACKER & MARKET CALENDAR ---
class GoldMarketSentinel:
    def __init__(self):
        self.compass = MacroCompass()
        self.smc = SMCEngine()
        self.notifier = TelegramNotifier()

        self.last_signal_key = None
        self.last_briefing_date = None
        self.last_summary_date = None
        self.current_bias = None

        # Daily Trade Ledger: Tracks outcomes of sent signals
        self.daily_trades = []

    def is_market_open(self) -> tuple:
        """
        Enforces real-world market hours:
        - Closed Friday 21:00 UTC through Sunday 21:00 UTC (Weekend)
        - Closed during Daily Rollover (21:00 - 22:00 UTC)
        """
        now_utc = datetime.now(timezone.utc)
        weekday = now_utc.weekday()  # Monday=0, Sunday=6
        hour = now_utc.hour

        # Friday after 21:00 UTC
        if weekday == 4 and hour >= 21:
            return False, "Weekend (Friday Market Close)"
        # Saturday all day
        if weekday == 5:
            return False, "Weekend (Market Closed)"
        # Sunday before 21:00 UTC
        if weekday == 6 and hour < 21:
            return False, "Weekend (Pre-Market Open)"
        # Weekday daily rollover (spreads blow out)
        if hour == 21:
            return False, "Daily Bank Rollover Blackout"

        return True, "Market Open"

    def get_session_poll_interval(self) -> int:
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        # London (07:00-11:00 UTC) & NY (12:00-16:00 UTC)
        if (7 <= hour < 11) or (12 <= hour < 16):
            return 180  # 3 mins
        return 300      # 5 mins

    def update_trade_outcomes(self, current_candle: dict):
        """Monitors live candles to check if open signals hit TP1, TP2, or SL."""
        high = current_candle["High"]
        low = current_candle["Low"]

        for trade in self.daily_trades:
            if trade["status"] == "OPEN":
                # BUY TRADE MONITORING
                if trade["direction"] == "BULLISH":
                    if low <= trade["sl"]:
                        trade["status"] = "HIT_SL"
                    elif high >= trade["tp2"]:
                        trade["status"] = "HIT_TP2"
                    elif high >= trade["tp1"]:
                        trade["status"] = "HIT_TP1"

                # SELL TRADE MONITORING
                elif trade["direction"] == "BEARISH":
                    if high >= trade["sl"]:
                        trade["status"] = "HIT_SL"
                    elif low <= trade["tp2"]:
                        trade["status"] = "HIT_TP2"
                    elif low <= trade["tp1"]:
                        trade["status"] = "HIT_TP1"

    def send_daily_summary(self):
        """Sends daily performance recap at 20:00 UTC (21:00 WAT)."""
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        if self.last_summary_date != today and now_utc.hour >= 20:
            total = len(self.daily_trades)
            if total == 0:
                msg = (
                    f"📊 <b>XAUUSD DAILY RECAP ({today.strftime('%d %b')})</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"💤 <b>Signals Generated:</b> 0\n"
                    f"<i>Market was in chop/consolidation. Zero forced trades. Capital preserved.</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
            else:
                tp1 = sum(1 for t in self.daily_trades if t["status"] in ["HIT_TP1", "HIT_TP2"])
                tp2 = sum(1 for t in self.daily_trades if t["status"] == "HIT_TP2")
                sl = sum(1 for t in self.daily_trades if t["status"] == "HIT_SL")
                open_trades = sum(1 for t in self.daily_trades if t["status"] == "OPEN")

                wins = tp1
                win_rate = round((wins / total) * 100, 1) if total > 0 else 0.0

                msg = (
                    f"📊 <b>XAUUSD DAILY PERFORMANCE RECAP</b>\n"
                    f"📅 <i>{today.strftime('%A, %d %B %Y')}</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 <b>Total Signals:</b> {total}\n"
                    f"✅ <b>Hit Target 1:</b> {tp1}\n"
                    f"🏆 <b>Hit Target 2:</b> {tp2}\n"
                    f"❌ <b>Hit Stop Loss:</b> {sl}\n"
                    f"⏳ <b>Active / Open:</b> {open_trades}\n"
                    f"📈 <b>Daily Win Rate:</b> <b>{win_rate}%</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ <i>Gold Autonomous Journal</i>"
                )

            self.notifier.send_message(msg)
            self.last_summary_date = today

    def run_cycle(self):
        market_open, reason = self.is_market_open()
        if not market_open:
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M UTC')}] Standby: {reason}")
            return

        now_utc = datetime.now(timezone.utc)

        # 1. Reset ledger at start of new day
        if self.last_briefing_date != now_utc.date():
            self.daily_trades = []

        # 2. Check Macro Bias
        macro_report = self.compass.calculate_macro_bias()
        new_bias = macro_report["macro_bias"]

        # Morning Briefing (07:30 WAT)
        if self.last_briefing_date != now_utc.date() and now_utc.hour >= 6:
            self.notifier.send_macro_briefing(macro_report)
            self.last_briefing_date = now_utc.date()

        # 3. SMC Scan
        smc_report = self.smc.scan_for_setups(macro_report)
        if smc_report.get("status") != "READY":
            return

        df = self.smc.fetch_data(interval="15min", outputsize=5)
        if not df.empty:
            curr_candle = {"High": df["High"].iloc[-1], "Low": df["Low"].iloc[-1]}
            self.update_trade_outcomes(curr_candle)

        # 4. Check Setup
        setup = smc_report.get("active_setup")
        if setup:
            setup_key = f"{setup['signal']}_{setup['entry_zone']}"
            if setup_key != self.last_signal_key:
                print(f"🚨 [GOLD SETUP TRIGGERED] Pinging Telegram...")
                self.notifier.send_trade_alert(setup, macro_report)
                self.last_signal_key = setup_key

                # Record in Daily Ledger
                try:
                    entry_val = float(str(setup["entry_zone"]).replace("$", "").strip())
                    self.daily_trades.append({
                        "direction": setup["direction"],
                        "entry": entry_val,
                        "sl": float(setup["stop_loss"]),
                        "tp1": float(setup["tp1"]),
                        "tp2": float(setup["tp2"]),
                        "status": "OPEN",
                        "time": now_utc.strftime("%H:%M")
                    })
                except Exception as e:
                    print(f"[Ledger Record Error]: {e}")

        # 5. Check Daily Performance Summary dispatch (21:00 WAT)
        self.send_daily_summary()

    def start(self):
        print("🪙 Autonomous Gold Sentinel Active with Live Trade Journal")
        while True:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[Cycle Error]: {e}")

            market_open, _ = self.is_market_open()
            sleep_time = self.get_session_poll_interval() if market_open else 900  # 15 mins on weekends
            time.sleep(sleep_time)

if __name__ == "__main__":
    t = threading.Thread(target=start_health_server, daemon=True)
    t.start()

    sentinel = GoldMarketSentinel()
    sentinel.start()
