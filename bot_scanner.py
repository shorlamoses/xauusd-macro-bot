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

# --- HTTP HEALTH SERVER (RESPONDS 200 OK TO CRON-JOB) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"XAUUSD_SENTINEL_OK_200")

    def log_message(self, format, *args):
        return  # Silence access logs

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"📡 Gold Sentinel Health Server online on port {port}")
    server.serve_forever()

# --- GOLD MARKET SENTINEL ---
class GoldMarketSentinel:
    def __init__(self):
        self.compass = MacroCompass()
        self.smc = SMCEngine()
        self.notifier = TelegramNotifier()
        self.last_signal_key = None
        self.last_briefing_date = None
        self.current_bias = None

    def get_session_context(self) -> tuple:
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        if (7 <= hour < 11) or (12 <= hour < 16):
            return True, "Active Killzone", 180  # 3 mins
        elif 6 <= hour < 18:
            return True, "Regular Market Hours", 300  # 5 mins
        else:
            return False, "Asian / Off-Hours", 600  # 10 mins

    def run_cycle(self):
        timestamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
        _, session_name, _ = self.get_session_context()

        # 1. Macro Bias
        macro_report = self.compass.calculate_macro_bias()
        new_bias = macro_report["macro_bias"]

        # Shift Alert
        if self.current_bias and new_bias != self.current_bias:
            self.notifier.send_message(
                f"🔄 <b>XAUUSD MACRO SHIFT:</b> <b>{new_bias}</b> ({macro_report['macro_score']}/5)\n"
                f"🎯 <code>{macro_report['trading_directive']}</code>"
            )
        self.current_bias = new_bias

        # Daily 07:30 WAT Briefing
        now_utc = datetime.now(timezone.utc)
        if self.last_briefing_date != now_utc.date() and now_utc.hour >= 6:
            self.notifier.send_macro_briefing(macro_report)
            self.last_briefing_date = now_utc.date()

        # 2. SMC Scan
        smc_report = self.smc.scan_for_setups(macro_report)
        if smc_report.get("status") != "READY":
            return

        levels = smc_report["levels"]
        print(f"[{timestamp}] {session_name} | Gold Spot: ${levels['current_price']} | Bias: {new_bias}")

        setup = smc_report.get("active_setup")
        if setup:
            setup_key = f"{setup['signal']}_{setup['entry_zone']}_{levels['asian_high']}"
            if setup_key != self.last_signal_key:
                print(f"🚨 [GOLD SETUP TRIGGERED] Pinging Telegram...")
                self.notifier.send_trade_alert(setup, macro_report)
                self.last_signal_key = setup_key

    def start(self):
        print("==================================================")
        print("🪙 Autonomous Gold Sentinel Active 24/5")
        print("==================================================")
        while True:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[Gold Scan Error]: {e}")

            _, _, sleep_sec = self.get_session_context()
            time.sleep(sleep_sec)

if __name__ == "__main__":
    # Start health server in background thread for Cron-job
    t = threading.Thread(target=start_health_server, daemon=True)
    t.start()

    # Start continuous scanner
    sentinel = GoldMarketSentinel()
    sentinel.start()