"""
Patrimonio Alert Bot
Controlla ogni mattina i prezzi di VWCE e SGLN.
Manda alert su Telegram se il prezzo scende sotto le soglie definite.
"""

import os
import datetime
import requests
import yfinance as yf
from supabase import create_client

# ─── CONFIGURAZIONE ───────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SUPABASE_URL     = "https://nmzgizjgpyyxyetqvccn.supabase.co"  # TODO: ripristinare os.environ dopo fix Railway
SUPABASE_KEY     = os.environ["SUPABASE_KEY"]
SUPABASE_USER_ID = os.environ["SUPABASE_USER_ID"]

# ─── PARAMETRI ALERT ──────────────────────────────────────────────────────────

STRUMENTI = {
    "VWCE": {
        "ticker": "VWCE.DE",
        "nome": "Vanguard FTSE All-World (VWCE)",
        "soglia_1": -7.0,
        "soglia_2": -12.0,
        "importo_1": 100,
        "importo_2": 200,
    },
    "SGLN": {
        "ticker": "SGLN.MI",
        "nome": "iShares Physical Gold (SGLN)",
        "soglia_1": -8.0,
        "soglia_2": -15.0,
        "importo_1": 100,
        "importo_2": 200,
    },
}

GIORNI_MEDIA     = 200
GIORNI_MIN_ALERT = 20
SOGLIA_LIQUIDITA = 15000

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def invia_messaggio(testo: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": testo, "parse_mode": "HTML"}
    r = requests.post(url, json=payload, timeout=10)
    r.raise_for_status()
    print(f">>> [TG] Messaggio inviato: {testo[:60]}...")

# ─── SUPABASE ─────────────────────────────────────────────────────────────────

def get_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def carica_dati_utente():
    sb = get_client()
    res = sb.table("patrimonio").select("dati,cfg,storico").eq("user_id", SUPABASE_USER_ID).single().execute()
    return res.data if res.data else {}

def carica_ultimi_alert(dati_utente: dict) -> dict:
    storico = dati_utente.get("storico") or {}
    if isinstance(storico, list):
        storico = {}
    return storico.get("bot_alert", {})

def salva_ultimi_alert(ultimi: dict):
    sb = get_client()
    res = sb.table("patrimonio").select("storico").eq("user_id", SUPABASE_USER_ID).single().execute()
    storico_attuale = (res.data.get("storico") or {}) if res.data else {}
    if isinstance(storico_attuale, list):
        storico_attuale = {}
    storico_attuale["bot_alert"] = ultimi
    sb.table("patrimonio").update({"storico": storico_attuale}).eq("user_id", SUPABASE_USER_ID).execute()
    print(">>> [DB] Ultimi alert salvati.")

# ─── CALCOLO PREZZI ───────────────────────────────────────────────────────────

def analizza_strumento(key: str, cfg: dict) -> dict | None:
    ticker = cfg["ticker"]
    print(f">>> [{key}] Scarico dati Yahoo Finance ({ticker})...")

    try:
        df = yf.download(ticker, period=f"{GIORNI_MEDIA + 50}d", progress=False)
    except Exception as e:
        errore = str(e)
        if "Too Many Requests" in errore or "RateLimit" in errore:
            print(f">>> [{key}] ❌ Yahoo Finance: limite richieste superato, riprova tra qualche minuto.")
        elif "No data found" in errore:
            print(f">>> [{key}] ❌ Yahoo Finance: nessun dato trovato per il ticker {ticker}.")
        else:
            print(f">>> [{key}] ❌ Yahoo Finance: errore — {errore}")
        return None

    print(f">>> [{key}] Righe scaricate: {len(df)}")

    if df.empty or len(df) < GIORNI_MEDIA:
        if df.empty:
            print(f">>> [{key}] ❌ Yahoo Finance: nessun dato ricevuto per {ticker} — possibile rate limit o ticker errato.")
        else:
            print(f">>> [{key}] ❌ Yahoo Finance: dati insufficienti — ricevute {len(df)} righe su {GIORNI_MEDIA} necessarie.")
        return None

    close = df["Close"].dropna().squeeze()
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
        print(f">>> [{key}] Nessuna soglia superata, tutto ok.")
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

    return f"""{titolo}

Prezzo oggi:   <b>{dati['prezzo']:.2f}</b>
Media 200gg:   {dati['media200']:.2f}
Scostamento:   <b>{dati['scostamento']:.1f}%</b> dalla media

Gap attuale:   €{gap:,.0f}
Liquidità:     €{liquidita:,.0f} ✓

{azione}

<i>{nota}</i>
<i>PAC mensile invariato — questo è extra.</i>"""

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    oggi = datetime.date.today().isoformat()
    print(f"\n{'='*50}")
    print(f"Patrimonio Alert Bot — {oggi}")
    print(f"{'='*50}\n")

    print(">>> Carico dati utente da Supabase...")
    dati_utente = carica_dati_utente()
    dati      = dati_utente.get("dati", {})
    liquidita = dati.get("liq", 0)
    print(f">>> Liquidità: €{liquidita:,.0f}")

    if liquidita < SOGLIA_LIQUIDITA:
        print(f">>> ⚠️ Liquidità sotto soglia (€{liquidita:,.0f} < €{SOGLIA_LIQUIDITA:,.0f}). Nessun alert inviato.")
        return

    ultimi_alert  = carica_ultimi_alert(dati_utente)
    alert_inviati = 0

    for key, cfg in STRUMENTI.items():
        print(f"\n>>> Analizzo {key}...")
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
        oro = dati.get("or", 0)
        tot_inv = az + dati.get("ob", 0) + oro
        cfg_mix = dati_utente.get("cfg", {}).get("mix", {"az": 75, "ob": 10, "or": 15})
        if key == "VWCE":
            gap = max(tot_inv * (cfg_mix.get("az", 75) / 100) - az, 0)
        else:
            gap = max(tot_inv * (cfg_mix.get("or", 15) / 100) - oro, 0)

        msg = costruisci_messaggio(risultato, liquidita, gap)
        invia_messaggio(msg)
        ultimi_alert[key] = oggi
        alert_inviati += 1

    salva_ultimi_alert(ultimi_alert)

    if alert_inviati == 0:
        print("\n>>> Nessun alert da inviare oggi.")
    else:
        print(f"\n>>> {alert_inviati} alert inviati.")

if __name__ == "__main__":
    main()
