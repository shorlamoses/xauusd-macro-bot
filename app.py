import streamlit as st
from datetime import datetime
from macro_engine import MacroCompass
from smc_engine import SMCEngine
from telegram_notifier import TelegramNotifier

# Page Configuration
st.set_page_config(
    page_title="XAUUSD Institutional Cockpit",
    page_icon="🪙",
    layout="wide"
)

st.title("🪙 XAUUSD Macro & SMC Trading Terminal")
st.caption(f"Real-Time Institutional Order Flow | Scanned at: {datetime.utcnow().strftime('%H:%M:%S UTC')}")

if st.button("🔄 Refresh Market Data"):
    st.rerun()

st.divider()

# Load Data
try:
    with st.spinner("Connecting to Intermarket & Spot Feeds..."):
        compass = MacroCompass()
        macro_report = compass.calculate_macro_bias()

        smc = SMCEngine()
        smc_report = smc.scan_for_setups(macro_report)
except Exception as e:
    st.error(f"❌ Error loading data: {e}")
    st.stop()

# 1. Macro Section
st.subheader("🧭 1. Macro & Intermarket Drivers")
score = macro_report.get("macro_score", 0)
badge = "🟢" if score >= 2 else ("🟩" if score > 0 else ("⚪" if score == 0 else ("🟧" if score >= -2 else "🔴")))

m1, m2, m3, m4 = st.columns(4)
m1.metric("Macro Bias", f"{badge} {macro_report.get('macro_bias')}", f"Score: {score}/5")
m2.metric("DXY Index", str(macro_report['dxy']['price']), macro_report['dxy']['trend'], delta_color="inverse")
m3.metric("US 10Y Yield", f"{macro_report['us10y']['yield']}%", macro_report['us10y']['trend'], delta_color="inverse")
m4.metric("10Y Real TIPS", f"{macro_report['real_yield_tips']['rate']}%", macro_report['real_yield_tips']['trend'], delta_color="inverse")

st.info(f"**Institutional Directive:** {macro_report.get('trading_directive')}")
st.divider()

# 2. SMC Section (Crash-Proof)
st.subheader("🎯 2. Trend & Setup Blueprint")
if smc_report.get("status") == "READY":
    levels = smc_report.get("levels", {})
    curr_price = levels.get("current_price", 0.0)
    pdh_val = levels.get("pdh", levels.get("asian_high", 0.0))
    pdl_val = levels.get("pdl", levels.get("asian_low", 0.0))

    setup = smc_report.get("active_setup")
    # Defensively handle NoneType setup to avoid AttributeError
    atr_display = setup.get("atr", "Active") if isinstance(setup, dict) else "Active"

    l1, l2, l3, l4 = st.columns(4)
    l1.metric("Spot Gold", f"${curr_price}")
    l2.metric("Asian Range", f"${levels.get('asian_low', 0)} - ${levels.get('asian_high', 0)}")
    l3.metric("Prev Day Range", f"${pdl_val} - ${pdh_val}")
    l4.metric("Market Volatility", f"ATR: {atr_display}")

    if setup:
        st.success(f"### 🚨 SETUP TRIGGERED: {setup['signal']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.write(f"**Entry Zone:** `{setup['entry_zone']}`")
        c2.write(f"**Stop Loss:** `${setup['stop_loss']}`")
        c3.write(f"**Target 1 (1.5R):** `${setup['tp1']}`")
        c4.write(f"**Target 2 (2.5R):** `${setup['tp2']}`")
        st.write(f"**Reason:** {setup['reason']}")
    else:
        st.warning(f"⏳ **STATUS: SCANNING.** Waiting for high-conviction 15m trend pullback.")

    # 3. Position Size Calculator
    st.divider()
    st.subheader("🧮 3. MT5 Position Size Calculator")
    calc1, calc2, calc3 = st.columns(3)
    with calc1:
        bal = st.number_input("Account Balance ($)", min_value=10.0, value=1000.0, step=50.0)
    with calc2:
        risk_pct = st.number_input("Risk Per Trade (%)", min_value=0.25, max_value=5.0, value=1.0, step=0.25)
    with calc3:
        sl_points = st.number_input("Stop Loss Distance ($)", min_value=1.0, value=5.0, step=0.50)

    risk_usd = bal * (risk_pct / 100.0)
    lot_size = risk_usd / (sl_points * 100.0)
    st.markdown(f"* **Amount at Risk:** `${risk_usd:.2f}` | **Recommended MT5 Lot:** **`{lot_size:.2f}` Lots**")
