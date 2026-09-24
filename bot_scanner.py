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

class GoldMarketSentinel:
    def __init__(self):
        self.compass = MacroCompass()
        self.smc = SMCEngine()
        self.notifier = TelegramNotifier()

        self.last_signal_key = None
        self.last_briefing_date = None
        self.last_summary_date = None
        self.last_core_direction = None
        self.daily_trades = []

    def is_market_open(self) -> tuple:
        now_utc = datetime.now(timezone.utc)
        weekday = now_utc.weekday()
        hour = now_utc.hour

        if weekday == 4 and hour >= 21:
            return False, "Weekend (Friday Close)"
        if weekday == 5:
            return False, "Weekend (Saturday)"
        if weekday == 6 and hour < 21:
            return False, "Weekend (Sunday Pre-Open)"
        if hour == 21:
            return False, "Daily Bank Rollover Blackout"

        return True, "Market Open"

    def is_high_liquidity_window(self) -> bool:
        """Limits scans to London (07-11 UTC) and NY (12-16 UTC) to save API credits."""
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        return (7 <= hour < 11) or (12 <= hour < 16)

    def update_trade_outcomes(self, current_candle: dict):
        if not current_candle:
            return
        high = current_candle["High"]
        low = current_candle["Low"]

        for trade in self.daily_trades:
            if trade["status"] == "OPEN":
                if trade["direction"] == "BULLISH":
                    if low <= trade["sl"]:
                        trade["status"] = "HIT_SL"
                    elif high >= trade["tp2"]:
                        trade["status"] = "HIT_TP2"
                    elif high >= trade["tp1"]:
                        trade["status"] = "HIT_TP1"
                elif trade["direction"] == "BEARISH":
                    if high >= trade["sl"]:
                        trade["status"] = "HIT_SL"
                    elif low <= trade["tp2"]:
                        trade["status"] = "HIT_TP2"
                    elif low <= trade["tp1"]:
                        trade["status"] = "HIT_TP1"

    def check_macro_shift(self, macro_report: dict):
        score = macro_report.get("macro_score", 0)
        direction = "BEARISH" if score <= -2.0 else ("BULLISH" if score >= 2.0 else "NEUTRAL")

        if self.last_core_direction is None:
            self.last_core_direction = direction
            return

        if direction != self.last_core_direction and direction != "NEUTRAL":
            self.last_core_direction = direction
            msg = (
                f"🔄 <b>XAUUSD MACRO REGIME SHIFT</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>New Bias:</b> <b>{macro_report['macro_bias']}</b> ({score}/5)\n"
                f"🎯 <b>Directive:</b> <code>{macro_report['trading_directive']}</code>"
            )
            self.notifier.send_message(msg)

    def send_daily_summary(self):
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        if self.last_summary_date != today and now_utc.hour >= 20:
            total = len(self.daily_trades)
            if total == 0:
                msg = (
                    f"📊 <b>XAUUSD DAILY RECAP ({today.strftime('%d %b')})</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"💤 <b>Signals Generated:</b> 0\n"
                    f"<i>Market lacked institutional volume/trend. Zero forced trades. Capital safe.</i>"
                )
            else:
                tp1 = sum(1 for t in self.daily_trades if t["status"] in ["HIT_TP1", "HIT_TP2"])
                tp2 = sum(1 for t in self.daily_trades if t["status"] == "HIT_TP2")
                sl = sum(1 for t in self.daily_trades if t["status"] == "HIT_SL")
                win_rate = round((tp1 / total) * 100, 1)

                msg = (
                    f"📊 <b>XAUUSD DAILY PERFORMANCE RECAP</b>\n"
                    f"📅 <i>{today.strftime('%A, %d %B %Y')}</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 <b>Total Signals:</b> {total}\n"
                    f"✅ <b>Hit Target 1:</b> {tp1}\n"
                    f"🏆 <b>Hit Target 2:</b> {tp2}\n"
                    f"❌ <b>Hit Stop Loss:</b> {sl}\n"
                    f"📈 <b>Daily Win Rate:</b> <b>{win_rate}%</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
            self.notifier.send_message(msg)
            self.last_summary_date = today

    def run_cycle(self):
        market_open, reason = self.is_market_open()
        if not market_open:
            return

        now_utc = datetime.now(timezone.utc)

        if self.last_briefing_date != now_utc.date():
            self.daily_trades = []

        # 1. Macro Bias
        macro_report = self.compass.calculate_macro_bias()
        self.check_macro_shift(macro_report)

        if self.last_briefing_date != now_utc.date() and now_utc.hour >= 6:
            self.notifier.send_macro_briefing(macro_report)
            self.last_briefing_date = now_utc.date()

        # 2. SMC / Technical Scan (Single API call)
        smc_report = self.smc.scan_for_setups(macro_report)
        if smc_report.get("status") != "READY":
            return

        # Updates trade outcomes using candle already returned (saves 1 API call!)
        self.update_trade_outcomes(smc_report.get("candle"))

        setup = smc_report.get("active_setup")
        if setup:
            setup_key = f"{setup['signal']}_{setup['entry_zone']}"
            if setup_key != self.last_signal_key:
                print(f"🚨 [GOLD SETUP TRIGGERED] Pinging Telegram...")
                self.notifier.send_trade_alert(setup, macro_report)
                self.last_signal_key = setup_key

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
                    print(f"[Ledger Error]: {e}")

        self.send_daily_summary()

    def start(self):
        print("🪙 Autonomous Gold Sentinel Active (Optimized API Allocation)")
        while True:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[Gold Sentinel Exception]: {e}")

            # Sleep 5 minutes (300s) during session, 15 minutes off-session
            market_open, _ = self.is_market_open()
            sleep_time = 300 if (market_open and self.is_high_liquidity_window()) else 900
            time.sleep(sleep_time)

if __name__ == "__main__":
    t = threading.Thread(target=start_health_server, daemon=True)
    t.start()

    sentinel = GoldMarketSentinel()
    sentinel.start()
