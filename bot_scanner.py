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
        self.last_signal_time = None
        self.last_signal_key = None

    def is_killzone(self) -> tuple:
        """
        Identifies active high-probability institutional sessions.
        London Killzone: 07:00 - 10:00 UTC (08:00 - 11:00 WAT)
        New York Killzone: 12:00 - 15:00 UTC (13:00 - 16:00 WAT)
        """
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour

        if 7 <= hour < 10:
            return True, "London Killzone"
        elif 12 <= hour < 15:
            return True, "New York Killzone"
        return False, "Off-Hours"

    def run_cycle(self):
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        is_kz, session_name = self.is_killzone()

        print(f"[{timestamp}] Scanning... Session: {session_name}")

        # 1. Evaluate Macro Compass
        macro_report = self.compass.calculate_macro_bias()

        # 2. Scan SMC Price Action on Spot Gold
        smc_report = self.smc.scan_for_setups(macro_report)

        if smc_report.get("status") != "READY":
            print("  ↳ Waiting for live candle data...")
            return

        levels = smc_report["levels"]
        print(f"  ↳ Spot: ${levels['current_price']} | Asian: ${levels['asian_low']}-${levels['asian_high']} | Macro: {macro_report['macro_bias']}")

        setup = smc_report.get("active_setup")
        if setup:
            # Create a unique key so we only alert once per setup
            setup_key = f"{setup['signal']}_{setup['entry_zone']}_{levels['asian_high']}"
            
            if setup_key != self.last_signal_key:
                print(f"\n🚨 [SETUP FOUND] {setup['signal']} at {setup['entry_zone']}! Sending Telegram alert...")
                self.notifier.send_trade_alert(setup, macro_report)
                self.last_signal_key = setup_key
                self.last_signal_time = datetime.now()
            else:
                print("  ↳ Active setup already alerted. Waiting for next structure shift.")
        else:
            print("  ↳ No active liquidity sweep. Standing by.")

    def start(self, poll_interval_seconds=60):
        print("==================================================")
        print("🚀 XAUUSD Autonomous Market Sentinel Started")
        print("📡 Monitoring DXY, US10Y Yields, and Spot Gold (SMC)")
        print("==================================================")
        
        # Send startup confirmation to Telegram
        self.notifier.send_message("🤖 <b>XAUUSD Autonomous Sentinel is ONLINE</b>\nScanning London & NY Killzones for SMC setups.")

        while True:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[Cycle Error]: {e}")

            # Sleep until next check (default: every 60 seconds)
            time.sleep(poll_interval_seconds)

if __name__ == "__main__":
    sentinel = MarketSentinel()
    sentinel.start(poll_interval_seconds=60)