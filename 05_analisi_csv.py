# 05_analisi_csv.py
#
# Primo passo con pandas: leggere il CSV dei prezzi scaricato con lo script 04
# e fargli le prime domande.
#
# NOTA IMPORTANTE: da qui in avanti NON serve piu' montare il volume cifrato.
# I dati sono normali file di testo sulla tua macchina. La cassaforte serve solo
# quando si SCARICANO dati nuovi (cioe' quando serve il token).
#
# Cosa fa, in ordine:
#   1. trova il file 04_prezzi_*.csv piu' recente
#   2. lo legge e ne mostra la forma (quante righe, quante colonne, che tipi)
#   3. calcola il prezzo medio di ogni zona
#   4. calcola il prezzo medio per ogni ora del giorno (il "profilo" della giornata)
#
# Il risultato viene stampato a video E salvato in  energy-data\log\05_esito_<data_ora>.txt

import glob
import os
import sys
import traceback
from datetime import datetime

import pandas as pd

CARTELLA = os.path.dirname(os.path.abspath(__file__))
CARTELLA_LOG = os.path.join(CARTELLA, "log")
os.makedirs(CARTELLA_LOG, exist_ok=True)
FILE_ESITO = os.path.join(CARTELLA_LOG,
                          "05_esito_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".txt")


class Doppio:
    """Scrive contemporaneamente a video e nel file di resoconto."""

    def __init__(self, percorso, schermo):
        self.file = open(percorso, "w", encoding="utf-8")
        self.schermo = schermo

    def write(self, testo):
        self.file.write(testo)
        self.schermo.write(testo)

    def flush(self):
        self.file.flush()
        self.schermo.flush()


def principale():
    print("=== AVVIO", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "===")
    print("Resoconto:", FILE_ESITO)
    print()

    # 1) QUALE FILE LEGGIAMO ---------------------------------------------
    # I nomi hanno la data e l'ora dentro, quindi prendiamo l'ultimo in ordine
    # alfabetico: e' il piu' recente.
    elenco = sorted(glob.glob(os.path.join(CARTELLA_LOG, "04_prezzi_*.csv")))
    if not elenco:
        print("Non trovo nessun file 04_prezzi_*.csv in", CARTELLA_LOG)
        print("Prima lancia lo script 04 (con il volume montato).")
        return
    percorso = elenco[-1]
    print("File letto:", os.path.basename(percorso))
    print("(e' il piu' recente fra", len(elenco), "file di prezzi trovati)")
    print()

    # 2) LEGGIAMO IL CSV IN UNA TABELLA ----------------------------------
    # read_csv fa tutto da solo: prima riga = nomi delle colonne, virgola =
    # separatore, e capisce da se' che i numeri sono numeri.
    dati = pd.read_csv(percorso)

    print("La tabella ha", dati.shape[0], "righe e", dati.shape[1], "colonne")
    print("Colonne:", list(dati.columns))
    print()
    print("Prime 5 righe (mostro 3 colonne su 5, altrimenti non ci stanno):")
    print(dati[["zona", "ora_italiana", "prezzo_eur_mwh"]].head())
    print()
    print("Tipi di dato:")
    print(dati.dtypes)
    print()
    print("Le zone presenti sono", dati["zona"].nunique(), ":")
    print(sorted(dati["zona"].unique()))
    print()

    # 3) DOMANDA: quanto costa in media l'energia in ogni zona? -----------
    # groupby("zona") divide la tabella in gruppi (uno per zona);
    # ["prezzo_eur_mwh"] sceglie la colonna dei prezzi; .mean() fa la media.
    print("Prezzo medio per zona (EUR/MWh):")
    media_per_zona = (dati.groupby("zona")["prezzo_eur_mwh"]
                      .mean()
                      .round(2)
                      .sort_values(ascending=False))
    print(media_per_zona)
    print()
    print("Questi numeri devono combaciare con la tabella RIEPILOGO dello")
    print("script 04: se combaciano, il riempimento dei quarti d'ora e' corretto.")
    print()

    # 4) DOMANDA: a che ora del giorno l'energia costa di piu'? -----------
    # L'ora la ricaviamo dalla colonna "ora_italiana", che e' testo.
    # to_datetime la trasforma in una vera data/ora; .dt.hour ne prende l'ora.
    dati["quando"] = pd.to_datetime(dati["ora_italiana"], format="%Y-%m-%d %H:%M")
    dati["ora_del_giorno"] = dati["quando"].dt.hour

    print("Prezzo medio per ora del giorno (tutte le zone, tutti i giorni):")
    per_ora = dati.groupby("ora_del_giorno")["prezzo_eur_mwh"].mean().round(2)
    for ora, prezzo in per_ora.items():
        barra = "#" * int(prezzo / 10)
        print("  %2d:00  %7.2f  %s" % (ora, prezzo, barra))
    print()
    print("Ora piu' economica:", per_ora.idxmin(), "->", per_ora.min(), "EUR/MWh")
    print("Ora piu' cara     :", per_ora.idxmax(), "->", per_ora.max(), "EUR/MWh")


SCHERMO = sys.stdout
RESOCONTO = Doppio(FILE_ESITO, SCHERMO)
sys.stdout = RESOCONTO

try:
    principale()
except Exception as errore:
    print("ERRORE:", type(errore).__name__, errore)
    print("Dettagli tecnici:")
    print(traceback.format_exc())
else:
    print()
    print("FINE: esecuzione conclusa senza errori.")
finally:
    RESOCONTO.flush()
    RESOCONTO.file.close()
    sys.stdout = SCHERMO
