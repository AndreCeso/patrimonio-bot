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

# ─── CONFIGURAZIONE ───────────────────────────────────────────────────────────
# Questi valori vengono letti dalle variabili d'ambiente su Railway

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SUPABASE_URL     = os.environ["SUPABASE_URL"]
SUPABASE_KEY     = os.environ["SUPABASE_KEY"]
SUPABASE_USER_ID = os.environ["SUPABASE_USER_ID"]

# ─── PARAMETRI ALERT (modifica qui le soglie) ─────────────────────────────────

STRUMENTI = {
    "VWCE": {
        "ticker": "VWCE.DE",          # ticker Yahoo Finance
        "nome": "Vanguard FTSE All-World (VWCE)",
        "soglia_1": -7.0,             # % sotto media 200gg → livello 1
        "soglia_2": -12.0,            # % sotto media 200gg → livello 2
        "importo_1": 100,             # € da comprare livello 1
        "importo_2": 200,             # € da comprare livello 2
    },
    "SGLN": {
        "ticker": "SGLN.MI",          # ticker Yahoo Finance (Milano)
        "nome": "iShares Physical Gold (SGLN)",
        "soglia_1": -8.0,
        "soglia_2": -15.0,
        "importo_1": 100,
        "importo_2": 200,
    },
}

GIORNI_MEDIA       = 200    # giorni per la media mobile
GIORNI_MIN_ALERT   = 20     # giorni minimi tra un alert e l'altro per strumento
SOGLIA_LIQUIDITA   = 15000  # € — alert soppresso se liquidità sotto questa cifra

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def invia_messaggio(testo: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": testo,
        "parse_mode": "HTML",
    }
    r = requests.post(url, json=payload, timeout=10)
    r.raise_for_status()
    print(f"[TG] Messaggio inviato: {testo[:60]}...")

# ─── SUPABASE ─────────────────────────────────────────────────────────────────

def get_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def carica_dati_utente():
    sb = get_client()
    res = sb.table("patrimonio").select("dati,cfg,storico").eq("user_id", SUPABASE_USER_ID).single().execute()
    return res.data if res.data else {}

def carica_ultimi_alert(dati_utente: dict) -> dict:
    """
    Legge la data degli ultimi alert dalla colonna 'storico' su Supabase.
    Usa la chiave 'bot_alert' dentro storico per non interferire con i dati del tracker.
    """
    storico = dati_utente.get("storico") or {}
    return storico.get("bot_alert", {})

def salva_ultimi_alert(ultimi: dict):
    """
    Salva la data degli ultimi alert nella colonna 'storico' su Supabase.
    Fa un merge parziale per non sovrascrivere gli altri dati in storico.
    """
    sb = get_client()
    # Prima legge lo storico attuale
    res = sb.table("patrimonio").select("storico").eq("user_id", SUPABASE_USER_ID).single().execute()
    storico_attuale = (res.data.get("storico") or {}) if res.data else {}
    # Aggiorna solo la chiave bot_alert
    storico_attuale["bot_alert"] = ultimi
    sb.table("patrimonio").update({"storico": storico_attuale}).eq("user_id", SUPABASE_USER_ID).execute()
    print("[DB] Ultimi alert salvati su Supabase.")

# ─── CALCOLO PREZZI ───────────────────────────────────────────────────────────

def analizza_strumento(key: str, cfg: dict) -> dict | None:
    """
    Scarica i prezzi, calcola la media 200gg e lo scostamento.
    Restituisce un dict con i dati se lo scostamento supera una soglia, altrimenti None.
    """
    ticker = cfg["ticker"]
    print(f"[{key}] Scarico dati da Yahoo Finance ({ticker})...")

    df = yf.download(ticker, period=f"{GIORNI_MEDIA + 50}d", progress=False)
    if df.empty or len(df) < GIORNI_MEDIA:
        print(f"[{key}] Dati insufficienti ({len(df)} giorni), skip.")
        return None

    close = df["Close"].dropna()
    prezzo_oggi = float(close.iloc[-1])
    media200    = float(close.tail(GIORNI_MEDIA).mean())
    scostamento = (prezzo_oggi - media200) / media200 * 100

    print(f"[{key}] Prezzo: {prezzo_oggi:.2f} | Media 200gg: {media200:.2f} | Scostamento: {scostamento:.2f}%")

    # determina il livello dell'alert
    if scostamento <= cfg["soglia_2"]:
        livello = 2
        importo = cfg["importo_2"]
    elif scostamento <= cfg["soglia_1"]:
        livello = 1
        importo = cfg["importo_1"]
    else:
        return None  # nessun alert

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

    # carica dati utente da Supabase
    print("Carico dati utente da Supabase...")
    dati_utente = carica_dati_utente()
    dati      = dati_utente.get("dati", {})
    liquidita = dati.get("liq", 0)
    print(f"Liquidità: €{liquidita:,.0f}")

    # controlla soglia liquidità
    if liquidita < SOGLIA_LIQUIDITA:
        print(f"⚠ Liquidità sotto soglia (€{liquidita} < €{SOGLIA_LIQUIDITA}). Nessun alert inviato.")
        return

    # carica ultimi alert da Supabase (non da file locale)
    ultimi_alert = carica_ultimi_alert(dati_utente)

    alert_inviati = 0

    for key, cfg in STRUMENTI.items():
        # controlla se l'alert è stato inviato di recente
        ultimo = ultimi_alert.get(key)
        if ultimo:
            giorni_passati = (datetime.date.today() - datetime.date.fromisoformat(ultimo)).days
            if giorni_passati < GIORNI_MIN_ALERT:
                print(f"[{key}] Alert già inviato {giorni_passati} giorni fa, skip.")
                continue

        # analizza lo strumento
        risultato = analizza_strumento(key, cfg)
        if risultato is None:
            print(f"[{key}] Nessun alert.")
            continue

        # calcola gap
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

        # costruisci e invia il messaggio
        msg = costruisci_messaggio(risultato, liquidita, gap)
        invia_messaggio(msg)

        # aggiorna data ultimo alert
        ultimi_alert[key] = oggi
        alert_inviati += 1

    salva_ultimi_alert(ultimi_alert)

    if alert_inviati == 0:
        print("\nNessun alert da inviare oggi.")
    else:
        print(f"\n{alert_inviati} alert inviati.")

if __name__ == "__main__":
    main()
