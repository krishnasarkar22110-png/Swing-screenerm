import io
import datetime as dt
import requests
import pandas as pd
import yfinance as yf
import streamlit as st

st.set_page_config(page_title="स्विंग स्क्रीनर", layout="wide")
st.title("स्विंग ट्रेडिंग स्क्रीनर: बिकवाली वाले शेयर")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/csv,*/*",
}

# ---------- पिछले 4 कारोबारी दिनों की तारीखें ----------
def last_trading_days(n=4):
    days = []
    d = dt.date.today()
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    return days

# ---------- NSE डिलीवरी रिपोर्ट ----------
@st.cache_data(ttl=3600)
def get_delivery(day):
    ds = day.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ds}.csv"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return None
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        df = df[df["SERIES"].str.strip() == "EQ"]
        df["DELIV_PER"] = pd.to_numeric(df["DELIV_PER"], errors="coerce")
        df["TTL_TRD_QNTY"] = pd.to_numeric(df["TTL_TRD_QNTY"], errors="coerce")
        return df[["SYMBOL", "DELIV_PER", "TTL_TRD_QNTY"]]
    except Exception:
        return None

# ---------- थ्री कैंडल स्विंग हाई ----------
def swing_high_recent(df, lookback=6):
    highs = df["High"].values
    for i in range(len(highs) - 2, len(highs) - 2 - lookback, -1):
        if i < 1:
            break
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            return True
    return False

# ---------- बेयरिश ऑर्डर ब्लॉक (सरल रूप) ----------
# आख़िरी ऊपर वाली कैंडल, जिसके बाद तेज़ गिरावट आई हो, उसका जोन
def near_bearish_ob(df):
    d = df.tail(30).reset_index(drop=True)
    for i in range(len(d) - 4, 0, -1):
        up = d.loc[i, "Close"] > d.loc[i, "Open"]
        drop = d.loc[i + 1, "Close"] < d.loc[i, "Low"]
        if up and drop:
            lo, hi = d.loc[i, "Low"], d.loc[i, "High"]
            last = d.loc[len(d) - 1, "Close"]
            return lo * 0.99 <= last <= hi * 1.01
    return False

# ---------- साइडबार ----------
st.sidebar.header("फ़िल्टर")
min_deliv = st.sidebar.slider("आख़िरी दिन न्यूनतम डिलीवरी %", 0, 100, 40)
vol_mult = st.sidebar.slider("वॉल्यूम औसत का कितना गुना", 1.0, 5.0, 1.5)
use_ob = st.sidebar.checkbox("ऑर्डर ब्लॉक शर्त लगाएँ", value=False)
use_swing = st.sidebar.checkbox("थ्री कैंडल स्विंग हाई शर्त लगाएँ", value=True)

symbols_text = st.sidebar.text_area(
    "शेयरों के नाम (NSE, कॉमा से अलग)",
    "RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK,SBIN,ITC,LT,AXISBANK,TATAMOTORS",
)
symbols = [s.strip().upper() for s in symbols_text.split(",") if s.strip()]

if st.button("स्कैन करें"):
    days = last_trading_days(4)
    deliv = {}
    for d in days:
        x = get_delivery(d)
        if x is not None:
            deliv[d] = x.set_index("SYMBOL")

    if not deliv:
        st.error("NSE का डेटा नहीं मिला। शायद आज का डेटा अभी जारी नहीं हुआ, थोड़ी देर बाद कोशिश कीजिए।")
        st.stop()

    rows = []
    bar = st.progress(0)
    for n, sym in enumerate(symbols):
        bar.progress((n + 1) / len(symbols))
        try:
            df = yf.download(sym + ".NS", period="3mo", interval="1d", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if len(df) < 25:
                continue

            # भाव ऊपर चढ़ा हो: 50 दिन औसत के ऊपर या पिछले 5 दिन में बढ़त
            up_move = df["Close"].iloc[-1] > df["Close"].iloc[-5]
            if not up_move:
                continue

            avg_vol = df["Volume"].tail(20).mean()
            if df["Volume"].iloc[-1] < vol_mult * avg_vol:
                continue

            if use_swing and not swing_high_recent(df):
                continue
            if use_ob and not near_bearish_ob(df):
                continue

            row = {"शेयर": sym, "भाव": round(float(df["Close"].iloc[-1]), 2)}
            ok = True
            for d in sorted(deliv.keys(), reverse=True):
                t = deliv[d]
                label = d.strftime("%d-%b")
                if sym in t.index:
                    row[f"डिलीवरी% {label}"] = round(float(t.loc[sym, "DELIV_PER"]), 1)
                    row[f"ट्रेड मात्रा {label}"] = int(t.loc[sym, "TTL_TRD_QNTY"])
                else:
                    row[f"डिलीवरी% {label}"] = None
                    row[f"ट्रेड मात्रा {label}"] = None
            latest = sorted(deliv.keys(), reverse=True)[0].strftime("%d-%b")
            dv = row.get(f"डिलीवरी% {latest}")
            if dv is None or dv < min_deliv:
                continue
            rows.append(row)
        except Exception:
            continue
    bar.empty()

    if rows:
        st.success(f"{len(rows)} शेयर मिले")
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    else:
        st.warning("कोई शेयर नहीं मिला। फ़िल्टर थोड़े ढीले कीजिए।")
