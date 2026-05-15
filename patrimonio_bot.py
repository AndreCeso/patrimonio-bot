"""
Patrimonio Alert Bot
Controlla ogni mattina i prezzi di VWCE e SGLN.
Manda alert su Telegram se il prezzo scende sotto le soglie definite.
"""

import os
import json
import datetime
import requests
import yfinance as yf
from supabase import create_client

print(">>> [1] Import completati")

# ─── CONFIGURAZIONE ───────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SUPABASE_URL     = os.environ["SUPABASE_URL"]
SUPABASE_KEY     = os.environ["SUPABASE_KEY"]
SUPABASE_USER_ID = os.environ["SUPABASE_USER_ID"]

print(">>> [2] Variabili d'ambiente lette")
print(f">>> SUPABASE_URL = {SUPABASE_URL}")

# ─── PARAMETRI ALERT ──────────────────────────────────────────────────────────

STRUMENTI = {
    "VWCE": {
        "ticker": "VWCE.DE",
        "nome": "Vanguard FTSE All-World (VWCE)",
        "soglia_1": 99.0,   # TEST — rimettere a -7.0
        "soglia_2": 50.0,   # TEST — rimettere a -12.0
        "importo_1": 100,
        "importo_2": 200,
    },
    "SGLN": {
        "ticker": "SGLN.MI",
        "nome": "iShares Physical Gold (SGLN)",
        "soglia_1": 99.0,   # TEST — rimettere a -8.0
        "soglia_2": 50.0,   # TEST — rimettere a -15.0
        "importo_1": 100,
        "importo_2": 200,
    },
}

GIORNI_MEDIA       = 200
GIORNI_MIN_ALERT   = 20
SOGLIA_LIQUIDITA   = 0      # TEST — rimettere a 15000

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def invia_messaggio(testo: str):
    print(">>> [TG] Invio messaggio Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": testo,
        "parse_mode": "HTML",
    }
    r = requests.post(url, json=payload, timeout=10)
    r.raise_for_status()
    print(f">>> [TG] Messaggio inviato OK: {testo[:60]}...")

# ─── SUPABASE ─────────────────────────────────────────────────────────────────

def get_client():
    print(">>> [DB] Creo client Supabase...")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print(">>> [DB] Client Supabase creato OK")
    return client

def carica_dati_utente():
    print(">>> [DB] Carico dati utente...")
    sb = get_client()
    res = sb.table("patrimonio").select("dati,cfg,storico").eq("user_id", SUPABASE_USER_ID).single().execute()
    print(f">>> [DB] Dati ricevuti: {res.data is not None}")
    return res.data if res.data else {}

def carica_ultimi_alert(dati_utente: dict) -> dict:
    storico = dati_utente.get("storico") or {}
    if isinstance(storico, list):
        storico = {}
    ultimi = storico.get("bot_alert", {})
    print(f">>> [DB] Ultimi alert: {ultimi}")
    return ultimi

def salva_ultimi_alert(ultimi: dict):
    print(">>> [DB] Salvo ultimi alert su Supabase...")
    sb = get_client()
    res = sb.table("patrimonio").select("storico").eq("user_id", SUPABASE_USER_ID).single().execute()
    storico_attuale = (res.data.get("storico") or {}) if res.data else {}
    storico_attuale["bot_alert"] = ultimi
    sb.table("patrimonio").update({"storico": storico_attuale}).eq("user_id", SUPABASE_USER_ID).execute()
    print(">>> [DB] Ultimi alert salvati OK")

# ─── CALCOLO PREZZI ───────────────────────────────────────────────────────────

def analizza_strumento(key: str, cfg: dict) -> dict | None:
    ticker = cfg["ticker"]
    print(f">>> [{key}] Scarico dati Yahoo Finance ({ticker})...")

    df = yf.download(ticker, period=f"{GIORNI_MEDIA + 50}d", progress=False)
    print(f">>> [{key}] Righe scaricate: {len(df)}")

    if df.empty or len(df) < GIORNI_MEDIA:
        print(f">>> [{key}] Dati insufficienti, skip.")
        return None

    close = df["Close"].dropna()
    prezzo_oggi = float(close.iloc[-1])
    media200    = float(close.tail(GIORNI_MEDIA).mean())
    scostamento = (prezzo_oggi - media200) / media200 * 100

    print(f">>> [{key}] Prezzo: {prezzo_oggi:.2f} | Media 200gg: {media200:.2f} | Scostamento: {scostamento:.2f}%")

    if scostamento <= cfg["soglia_2"]:
        livello = 2
        importo = cfg["importo_2"]
    elif scostamento <= cfg["soglia_1"]:
        livello = 1
        importo = cfg["importo_1"]
    else:
        print(f">>> [{key}] Nessuna soglia superata, nessun alert.")
        return None

    print(f">>> [{key}] ALERT livello {livello}!")
    return {
        "key": key,
        "nome": cfg["nome"],
        "prezzo": prezzo_oggi,
        "media200": media200,
        "scostamento": scostamento,
        "livello": livello,
        "importo": importo,
    }

# ─── COSTRUISCI MESSAGGIO ─────────────────────────────────────────────────────

def costruisci_messaggio(dati: dict, liquidita: float, gap: float) -> str:
    emoji_livello = "🚨" if dati["livello"] == 2 else "📉"
    titolo = f"{emoji_livello} <b>{dati['nome']}</b>"

    if dati["livello"] == 2:
        azione = f"⚡️ <b>ACQUISTA ORA €{dati['importo']} su Trade Republic</b>"
        nota   = "Correzione importante — storicamente rara e con forti rendimenti nel medio termine."
    else:
        azione = f"👉 Considera acquisto extra <b>€{dati['importo']}</b> su Trade Republic"
        nota   = "Occasione di acquisto extra rispetto al PAC mensile."

    msg = f"""{titolo}

Prezzo oggi:   <b>{dati['prezzo']:.2f}</b>
Media 200gg:   {dati['media200']:.2f}
Scostamento:   <b>{dati['scostamento']:.1f}%</b> dalla media

Gap attuale:   €{gap:,.0f}
Liquidità:     €{liquidita:,.0f} ✓

{azione}

<i>{nota}</i>
<i>PAC mensile invariato — questo è extra.</i>"""

    return msg

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    oggi = datetime.date.today().isoformat()
    print(f"\n{'='*50}")
    print(f"Patrimonio Alert Bot — {oggi}")
    print(f"{'='*50}\n")

    print(">>> [3] Inizio main()")

    dati_utente = carica_dati_utente()
    dati      = dati_utente.get("dati", {})
    liquidita = dati.get("liq", 0)
    print(f">>> [4] Liquidità: €{liquidita:,.0f}")

    if liquidita < SOGLIA_LIQUIDITA:
        print(f">>> [!] Liquidità sotto soglia (€{liquidita} < €{SOGLIA_LIQUIDITA}). Stop.")
        return

    ultimi_alert = carica_ultimi_alert(dati_utente)
    alert_inviati = 0

    for key, cfg in STRUMENTI.items():
        print(f"\n>>> [5] Analizzo {key}...")
        ultimo = ultimi_alert.get(key)
        if ultimo:
            giorni_passati = (datetime.date.today() - datetime.date.fromisoformat(ultimo)).days
            if giorni_passati < GIORNI_MIN_ALERT:
                print(f">>> [{key}] Alert già inviato {giorni_passati} giorni fa, skip.")
                continue

        risultato = analizza_strumento(key, cfg)
        if risultato is None:
            continue

        az  = dati.get("az", 0)
        ob  = dati.get("ob", 0)
        oro = dati.get("or", 0)
        tot_inv = az + ob + oro
        cfg_mix = dati_utente.get("cfg", {}).get("mix", {"az": 75, "ob": 10, "or": 15})
        if key == "VWCE":
            target = tot_inv * (cfg_mix.get("az", 75) / 100)
            gap = max(target - az, 0)
        else:
            target = tot_inv * (cfg_mix.get("or", 15) / 100)
            gap = max(target - oro, 0)

        msg = costruisci_messaggio(risultato, liquidita, gap)
        invia_messaggio(msg)
        ultimi_alert[key] = oggi
        alert_inviati += 1

    salva_ultimi_alert(ultimi_alert)

    print(f"\n>>> [6] Fine. Alert inviati: {alert_inviati}")

if __name__ == "__main__":
    main()
