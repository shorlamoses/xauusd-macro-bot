import streamlit as st
from datetime import datetime
from macro_engine import MacroCompass
from smc_engine import SMCEngine
from telegram_notifier import TelegramNotifier

# 1. Page Configuration
st.set_page_config(
    page_title="XAUUSD Institutional Cockpit",
    page_icon="🪙",
    layout="wide"
)

st.title("🪙 XAUUSD Macro & SMC Trading Terminal")
st.caption(f"Real-Time Institutional Order Flow & Macro Intelligence | Last scan: {datetime.utcnow().strftime('%H:%M:%S UTC')}")

# Refresh button
if st.button("🔄 Refresh Market Data"):
    st.rerun()

st.divider()

# 2. Fetch Data with Error Catching
try:
    with st.spinner("Connecting to Intermarket & Spot Feeds..."):
        compass = MacroCompass()
        macro_report = compass.calculate_macro_bias()

        smc = SMCEngine()
        smc_report = smc.scan_for_setups(macro_report)
except Exception as e:
    st.error(f"❌ Error loading data: {e}")
    st.stop()

# ----------------- SECTION 1: MACRO INTELLIGENCE -----------------
st.subheader("🧭 1. Macro & Intermarket Drivers")

score = macro_report.get("macro_score", 0)
if score >= 3:
    badge = "🟢"
elif score > 0:
    badge = "🟩"
elif score == 0:
    badge = "⚪"
elif score >= -2:
    badge = "🟧"
else:
    badge = "🔴"

m_col1, m_col2, m_col3, m_col4 = st.columns(4)
m_col1.metric("Macro Bias", f"{badge} {macro_report.get('macro_bias')}", f"Score: {score}/5")
m_col2.metric("DXY (US Dollar)", str(macro_report['dxy']['price']), macro_report['dxy']['trend'])
m_col3.metric("US 10Y Yield", f"{macro_report['us10y']['yield']}%", macro_report['us10y']['trend'])
m_col4.metric("10Y Real TIPS", f"{macro_report['real_yield_tips']['rate']}%", macro_report['real_yield_tips']['trend'])

st.info(f"**Institutional Directive:** {macro_report.get('trading_directive')}")

st.divider()

# ----------------- SECTION 2: SMC LIQUIDITY & SETUP -----------------
st.subheader("🎯 2. SMC Price Action & Trade Blueprint")

if smc_report.get("status") == "READY":
    levels = smc_report["levels"]
    curr_price = levels["current_price"]

    l_col1, l_col2, l_col3, l_col4 = st.columns(4)
    l_col1.metric("Spot Gold (XAUUSD)", f"${curr_price}")
    l_col2.metric("Asian Range", f"${levels['asian_low']} - ${levels['asian_high']}")
    l_col3.metric("Prev Day Range", f"${levels['pdl']} - ${levels['pdh']}")
    l_col4.metric("Active FVGs", f"{len(smc_report.get('fvgs', []))} detected")

    setup = smc_report.get("active_setup")
    if setup:
        st.success(f"### 🚨 SETUP TRIGGERED: {setup['signal']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.write(f"**Entry Zone:** `{setup['entry_zone']}`")
        c2.write(f"**Stop Loss:** `${setup['stop_loss']}`")
        c3.write(f"**Target 1 (1:2):** `${setup['tp1']}`")
        c4.write(f"**Target 2 (Liquidity):** `${setup['tp2']}`")
        st.write(f"**Technical Reason:** {setup['reason']}")
    else:
        st.warning(f"⏳ **STATUS: SCANNING.** Waiting for price to sweep Asian High (`${levels['asian_high']}`) or Asian Low (`${levels['asian_low']}`).")

    # ----------------- SECTION 3: LOT SIZE CALCULATOR -----------------
    st.divider()
    st.subheader("🧮 3. MT5 Position Size Calculator")

    calc1, calc2, calc3 = st.columns(3)
    with calc1:
        account_bal = st.number_input("Account Balance ($)", min_value=10.0, value=1000.0, step=50.0)
    with calc2:
        risk_pct = st.number_input("Risk Per Trade (%)", min_value=0.25, max_value=5.0, value=1.0, step=0.25)
    with calc3:
        sl_points = st.number_input("Stop Loss Distance ($)", min_value=0.50, value=3.50, step=0.50)

    risk_dollars = account_bal * (risk_pct / 100.0)
    # Gold: $1 move = $100 on 1.00 lot
    calc_lot = risk_dollars / (sl_points * 100.0)

    st.markdown(f"""
    * **Amount at Risk:** `${risk_dollars:.2f}`
    * **Recommended MT5 Lot Size:** **`{calc_lot:.2f}` Lots**
    """)
else:
    st.warning("⚠️ Waiting for Twelve Data market candles...")

st.divider()

# ----------------- SECTION 4: TELEGRAM PUSH BUTTON -----------------
st.subheader("📱 4. Send Intelligence to Phone")
if st.button("📲 Push Macro Briefing to Telegram Now"):
    notifier = TelegramNotifier()
    sent = notifier.send_macro_briefing(macro_report)
    if sent:
        st.success("✅ Macro briefing pushed to your Telegram!")
    else:
        st.error("❌ Failed to push. Check bot credentials in .env")