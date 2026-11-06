# 03_test_eia.py
#
# Prima chiamata reale all'API EIA, con resoconto salvato su file.
#
# Cosa fa, in ordine:
#   1. legge le chiavi dal volume cifrato (A:\secrets.env), senza mai stamparle
#   2. chiede all'API EIA i prezzi al dettaglio del Colorado (settore residenziale)
#   3. scrive TUTTO quello che succede dentro  energy-data\log\
#      Cosi' l'esito si puo' leggere dopo, senza copiare nulla dallo schermo.
#
# File prodotti a ogni esecuzione (data e ora nel nome, non si sovrascrivono):
#   energy-data\log\03_esito_<data_ora>.txt   -> resoconto, identico a quello a video
#   energy-data\log\03_dati_<data_ora>.json   -> i dati grezzi ricevuti da EIA
#
# SICUREZZA:
#   - i valori letti dal volume non vengono MAI stampati;
#   - ogni riga scritta (video e file) passa dalla funzione "nascondi", che
#     sostituisce quei valori con ***CHIAVE-NASCOSTA***;
#    - niente viene scritto dentro A: (il resoconto va nella cartella del progetto).
#
# Come si usa: montare il volume su A:, aprire questo file in IDLE, premere F5.

import json
import os
import sys
import traceback
from datetime import datetime

import requests

PERCORSO = r"A:\secrets.env"
INDIRIZZO = "https://api.eia.gov/v2/electricity/retail-sales/data"
MASCHERA = "***CHIAVE-NASCOSTA***"

# Qui finiscono i valori letti dal volume. La maschera li legge da questo
# dizionario, quindi si puo' riempire anche dopo che l'oggetto e' stato creato.
SEGRETI = {}

# Cartella dei resoconti: "log" accanto a questo script.
# os.path.abspath(__file__) e' il percorso completo di questo file; prendiamo
# solo la cartella che lo contiene.
try:
    CARTELLA_BASE = os.path.dirname(os.path.abspath(__file__))
except NameError:                      # solo se IDLE non ci dice dove siamo
    CARTELLA_BASE = os.getcwd()
CARTELLA_LOG = os.path.join(CARTELLA_BASE, "log")
os.makedirs(CARTELLA_LOG, exist_ok=True)   # crea la cartella se non c'e' gia'

# Un nome diverso per ogni esecuzione, con data e ora.
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_RESOCONTO = os.path.join(CARTELLA_LOG, "03_esito_" + MARCHIO + ".txt")
FILE_DATI = os.path.join(CARTELLA_LOG, "03_dati_" + MARCHIO + ".json")


def nascondi(testo):
    """Sostituisce ogni valore segreto con la maschera."""
    for valore in SEGRETI.values():
        # Solo valori lunghi: sostituire una stringa vuota (o di un carattere)
        # rovinerebbe il testo.
        if isinstance(valore, str) and len(valore) >= 8:
            testo = testo.replace(valore, MASCHERA)
    return testo


class Doppio:
    """Scrive nello stesso momento sullo schermo di IDLE e dentro il file.

    Ogni testo passa da nascondi(): cosi' la chiave non puo' uscire ne' a
    video ne' nel file, nemmeno attraverso un messaggio d'errore.
    """

    def __init__(self, percorso):
        self.file = open(percorso, "w", encoding="utf-8")
        self.schermo = sys.stdout        # lo schermo di IDLE, messo da parte

    def write(self, testo):
        testo = nascondi(testo)
        self.file.write(testo)
        self.file.flush()                # scritto subito su disco, anche se va in errore
        self.schermo.write(testo)
        self.schermo.flush()

    def flush(self):
        self.file.flush()
        self.schermo.flush()

    def chiudi(self):
        self.file.close()


def leggi_chiavi(percorso):
    """Legge un file .env e restituisce un dizionario {nome: valore}."""
    chiavi = {}
    with open(percorso, "r", encoding="utf-8") as file:
        for riga in file:
            riga = riga.strip()
            if riga == "" or riga.startswith("#"):
                continue
            if "=" in riga:
                nome, valore = riga.split("=", 1)
                chiavi[nome.strip()] = valore.strip()
    return chiavi


def scarica_prezzi(chiave):
    """Chiama l'API EIA e restituisce la risposta."""
    parametri = {
        "api_key": chiave,
        "frequency": "monthly",
        "data[]": "price",
        "facets[stateid][]": "CO",
        "facets[sectorid][]": "RES",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 5,
    }
    risposta = requests.get(INDIRIZZO, params=parametri, timeout=20)
    risposta.raise_for_status()
    return risposta


def principale():
    print("=== AVVIO", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "===")
    print("Resoconto      :", FILE_RESOCONTO)
    print("Dati grezzi    :", FILE_DATI)
    print()

    # --- 1) leggo le chiavi dal volume -----------------------------------
    print("Leggo le chiavi da", PERCORSO)
    chiavi = leggi_chiavi(PERCORSO)
    SEGRETI.update(chiavi)          # da qui in avanti ogni testo e' mascherato
    print("  chiavi trovate:", len(chiavi), "->", list(chiavi.keys()))
    print("  (i valori non vengono mai stampati)")
    print()

    chiave = chiavi.get("EIA_KEY", "")
    print("Chiave EIA:", len(chiave), "caratteri")
    if len(chiave) != 40:
        print("ATTENZIONE: una chiave EIA vera ha 40 caratteri. Non chiamo l'API.")
        return
    print("Lunghezza corretta: procedo.")
    print()

    # --- 2) chiamata all'API ---------------------------------------------
    print("Chiamo l'API EIA:")
    print("  indirizzo :", INDIRIZZO)
    print("  dati      : price (prezzo al dettaglio)")
    print("  stato     : CO (Colorado)")
    print("  settore   : RES (residenziale)")
    print("  frequenza : monthly (mensile)")
    print("  righe     : 5 (le piu' recenti)")
    risposta = scarica_prezzi(chiave)
    print("  stato HTTP:", risposta.status_code)
    dati = risposta.json()

    # --- 3) salvo i dati grezzi su file ----------------------------------
    testo_json = nascondi(json.dumps(dati, indent=2, ensure_ascii=False))
    with open(FILE_DATI, "w", encoding="utf-8") as file:
        file.write(testo_json)
    print("  dati grezzi salvati:", FILE_DATI)
    print()

    # --- 4) riassunto leggibile ------------------------------------------
    print("Sezioni della risposta:", list(dati.keys()))
    if "warnings" in dati:
        print("Avvisi di EIA:", dati["warnings"])

    serie = dati.get("response", {}).get("data", [])
    print("Righe ricevute:", len(serie))
    print("Prezzo al dettaglio - Colorado, settore residenziale (centesimi per kWh):")
    for riga in serie:
        print("   ", riga.get("period"), "->", riga.get("price"), riga.get("price-units", ""))


# --- esecuzione ----------------------------------------------------------
# Messi da parte i canali normali, cosi' li possiamo rimettere a posto alla fine.
SCHERMO = sys.stdout
SCHERMO_ERRORE = sys.stderr

RESOCONTO = Doppio(FILE_RESOCONTO)
sys.stdout = RESOCONTO
sys.stderr = RESOCONTO            # anche gli errori finiscono nel resoconto

try:
    principale()
except Exception:
    print()
    print("ERRORE (riportato per intero, con i valori segreti mascherati):")
    print(traceback.format_exc())
else:
    print()
    print("FINE: esecuzione conclusa senza errori.")
finally:
    sys.stdout = SCHERMO
    sys.stderr = SCHERMO_ERRORE
    RESOCONTO.chiudi()
    print()
    print("Resoconto scritto in:", FILE_RESOCONTO)
