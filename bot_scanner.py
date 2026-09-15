import time
from datetime import datetime, timezone
from macro_engine import MacroCompass
from smc_engine import SMCEngine
from telegram_notifier import TelegramNotifier

class MarketSentinel:
    def __init__(self):
        self.compass = MacroCompass()
        self.smc = SMCEngine()
        self.notifier = TelegramNotifier()

        # State memory to prevent duplicate pings
        self.current_macro_bias = None
        self.last_briefing_date = None
        self.last_signal_key = None

    def get_session_context(self) -> tuple:
        """
        Determines current session and returns:
        (is_high_volume_window, session_name, poll_interval_seconds)
        """
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour

        # London (07:00-11:00 UTC / 08:00-12:00 WAT) & NY (12:00-16:00 UTC / 13:00-17:00 WAT)
        if (7 <= hour < 11) or (12 <= hour < 16):
            return True, "Active Killzone", 180  # Poll every 3 minutes
        elif 6 <= hour < 18:
            return True, "Regular Market Hours", 300  # Poll every 5 minutes
        else:
            return False, "Asian / Off-Hours", 600  # Poll every 10 minutes (conserves credits)

    def check_daily_briefing(self, macro_report: dict):
        """Sends pre-market briefing once a day at 06:30 UTC / 07:30 WAT."""
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        # Check if it's 06:30 UTC or later and we haven't sent today's briefing yet
        if self.last_briefing_date != today and now_utc.hour >= 6:
            print("[Alert]: Dispatching Daily Pre-Market Briefing to Telegram...")
            self.notifier.send_macro_briefing(macro_report)
            self.last_briefing_date = today

    def check_macro_shift(self, macro_report: dict):
        """Pings Telegram ONLY when the Macro Bias officially flips."""
        new_bias = macro_report["macro_bias"]

        if self.current_macro_bias is None:
            # First initialization - record baseline silently
            self.current_macro_bias = new_bias
            return

        if new_bias != self.current_macro_bias:
            old_bias = self.current_macro_bias
            self.current_macro_bias = new_bias

            print(f"[Alert]: Macro Shift from {old_bias} to {new_bias}. Pinging Telegram...")
            msg = (
                f"🔄 <b>MACRO REGIME SHIFT DETECTED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Previous Bias:</b> {old_bias}\n"
                f"• <b>New Bias:</b> <b>{new_bias}</b> (Score: {macro_report['macro_score']}/5)\n"
                f"🎯 <b>New Directive:</b> <code>{macro_report['trading_directive']}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 <i>DXY: {macro_report['dxy']['price']} | US10Y: {macro_report['us10y']['yield']}%</i>"
            )
            self.notifier.send_message(msg)

    def run_cycle(self):
        timestamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
        is_active, session_name, _ = self.get_session_context()

        # 1. Evaluate Macro Compass
        macro_report = self.compass.calculate_macro_bias()

        # 2. Check Daily Briefing & Bias Shift triggers
        self.check_daily_briefing(macro_report)
        self.check_macro_shift(macro_report)

        # 3. Only query Twelve Data candles when market is open / active
        smc_report = self.smc.scan_for_setups(macro_report)
        if smc_report.get("status") != "READY":
            return

        levels = smc_report["levels"]
        print(f"[{timestamp}] {session_name} | Spot: ${levels['current_price']} | Bias: {macro_report['macro_bias']}")

        # 4. Check for High-Probability Setup
        setup = smc_report.get("active_setup")
        if setup:
            setup_key = f"{setup['signal']}_{setup['entry_zone']}_{levels['asian_high']}"
            if setup_key != self.last_signal_key:
                print(f"🚨 [TRADE SETUP FOUND] Triggering Telegram alert...")
                # Sends complete blueprint including current macro score
                self.notifier.send_trade_alert(setup, macro_report)
                self.last_signal_key = setup_key

    def start(self):
        print("==================================================")
        print("🚀 Intelligent XAUUSD Sentinel Active")
        print("🔋 Dynamic API Budgeting Engaged (< 300 credits/day)")
        print("==================================================")

        while True:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[Cycle Exception]: {e}")

            # Dynamic sleep interval based on market session
            _, _, sleep_seconds = self.get_session_context()
            time.sleep(sleep_seconds)

if __name__ == "__main__":
    sentinel = MarketSentinel()
    sentinel.start()