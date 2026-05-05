import os
import time
import json
import random
import requests
from datetime import datetime, time as dtime

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8732662024:AAHEBYAcrDJ_TQ1a0DQJ3GZkgIV6Q7jS41E")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "-1003895272714")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
CHECK_INTERVAL = 300  # 5 minutes

sent_alerts = set()

def is_market_hours():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE

def send_telegram_message(message):
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json().get("ok", False)
    except Exception as e:
        print(f"Error sending message: {e}")
        return False

def get_nse_option_chain(symbol="NIFTY"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/option-chain",
    }
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        time.sleep(1)
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        response = session.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error fetching option chain: {e}")
    return None

def analyze_option_chain(data, symbol="NIFTY"):
    if not data or "records" not in data:
        return None
    
    records = data["records"]
    underlying_value = records.get("underlyingValue", 0)
    expiry_dates = records.get("expiryDates", [])
    
    if not expiry_dates:
        return None
    
    nearest_expiry = expiry_dates[0]
    options = records.get("data", [])
    
    near_atm_options = []
    for option in options:
        if option.get("expiryDate") != nearest_expiry:
            continue
        strike = option.get("strikePrice", 0)
        if abs(strike - underlying_value) <= underlying_value * 0.02:
            near_atm_options.append(option)
    
    if not near_atm_options:
        return None
    
    total_call_oi = sum(o.get("CE", {}).get("openInterest", 0) for o in near_atm_options if "CE" in o)
    total_put_oi = sum(o.get("PE", {}).get("openInterest", 0) for o in near_atm_options if "PE" in o)
    
    if total_call_oi == 0 or total_put_oi == 0:
        return None
    
    pcr = total_put_oi / total_call_oi
    
    max_call_oi = 0
    max_call_strike = 0
    max_put_oi = 0
    max_put_strike = 0
    
    for option in options:
        if option.get("expiryDate") != nearest_expiry:
            continue
        ce_oi = option.get("CE", {}).get("openInterest", 0)
        pe_oi = option.get("PE", {}).get("openInterest", 0)
        strike = option.get("strikePrice", 0)
        if ce_oi > max_call_oi:
            max_call_oi = ce_oi
            max_call_strike = strike
        if pe_oi > max_put_oi:
            max_put_oi = pe_oi
            max_put_strike = strike
    
    return {
        "symbol": symbol,
        "spot": underlying_value,
        "expiry": nearest_expiry,
        "pcr": round(pcr, 2),
        "max_call_strike": max_call_strike,
        "max_put_strike": max_put_strike,
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
    }

def generate_signal(analysis):
    if not analysis:
        return None
    
    pcr = analysis["pcr"]
    spot = analysis["spot"]
    max_call = analysis["max_call_strike"]
    max_put = analysis["max_put_strike"]
    symbol = analysis["symbol"]
    expiry = analysis["expiry"]
    
    signal = None
    reason = ""
    
    if pcr < 0.7:
        signal = "BEARISH"
        reason = f"PCR={pcr} (Oversold calls, market may fall)"
    elif pcr > 1.3:
        signal = "BULLISH"
        reason = f"PCR={pcr} (Strong put writing, market may rise)"
    elif 0.9 <= pcr <= 1.1:
        signal = "NEUTRAL"
        reason = f"PCR={pcr} (Balanced OI)"
    
    if signal:
        resistance = max_call
        support = max_put
        
        alert_key = f"{symbol}_{signal}_{int(spot/50)*50}"
        if alert_key in sent_alerts:
            return None
        sent_alerts.add(alert_key)
        if len(sent_alerts) > 100:
            sent_alerts.clear()
        
        return {
            "signal": signal,
            "symbol": symbol,
            "spot": spot,
            "expiry": expiry,
            "support": support,
            "resistance": resistance,
            "pcr": pcr,
            "reason": reason
        }
    return None

def format_alert(signal_data):
    emoji_map = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}
    emoji = emoji_map.get(signal_data["signal"], "⚪")
    
    msg = f"""<b>{emoji} NiftyEdge Pro Alert</b>

<b>Symbol:</b> {signal_data["symbol"]}
<b>Signal:</b> {signal_data["signal"]} {emoji}
<b>Spot Price:</b> {signal_data["spot"]:,.0f}
<b>Expiry:</b> {signal_data["expiry"]}

<b>📊 Key Levels:</b>
• Support (Max PE OI): {signal_data["support"]:,}
• Resistance (Max CE OI): {signal_data["resistance"]:,}

<b>📈 PCR Analysis:</b>
• PCR: {signal_data["pcr"]}
• {signal_data["reason"]}

<b>⚠️ Disclaimer:</b> For educational purposes only. Not SEBI registered. Trade at your own risk.

🔔 <a href="https://im.page/niftyedgepro">Subscribe for more alerts</a>"""
    return msg

def send_morning_brief():
    now = datetime.now()
    msg = f"""<b>🌅 NiftyEdge Pro — Good Morning!</b>

Date: {now.strftime("%d %B %Y, %A")}
Market opens at 9:15 AM

📊 Today's scan: NIFTY & BANKNIFTY option chain
🔔 Alerts will be posted as signals emerge

Stay sharp. Trade smart.

<a href="https://im.page/niftyedgepro">👉 Subscribe to NiftyEdge Pro</a>"""
    send_telegram_message(msg)

def main():
    print(f"NiftyEdge Pro Bot started at {datetime.now()}")
    
    morning_brief_sent = False
    last_check_date = None
    
    while True:
        now = datetime.now()
        
        if now.date() != last_check_date:
            morning_brief_sent = False
            last_check_date = now.date()
        
        if is_market_hours():
            current_time = now.time()
            
            if not morning_brief_sent and current_time >= MARKET_OPEN:
                send_morning_brief()
                morning_brief_sent = True
                print(f"Morning brief sent at {now}")
            
            for symbol in ["NIFTY", "BANKNIFTY"]:
                print(f"Checking {symbol} option chain...")
                data = get_nse_option_chain(symbol)
                
                if data:
                    analysis = analyze_option_chain(data, symbol)
                    signal_data = generate_signal(analysis)
                    
                    if signal_data:
                        message = format_alert(signal_data)
                        success = send_telegram_message(message)
                        if success:
                            print(f"Alert sent for {symbol}: {signal_data['signal']}")
                        else:
                            print(f"Failed to send alert for {symbol}")
                else:
                    print(f"Could not fetch data for {symbol}")
                
                time.sleep(2)
            
            print(f"Next check in {CHECK_INTERVAL} seconds...")
            time.sleep(CHECK_INTERVAL)
        else:
            print(f"Market closed. Sleeping for 60 seconds... [{now.strftime('%H:%M')}]")
            time.sleep(60)

if __name__ == "__main__":
    main()
