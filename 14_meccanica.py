# 14_meccanica.py
#
# Verifiche di dettaglio sul crollo del 16/10. Nessun volume, solo file gia' salvati.
#
#   A) i due documenti di manutenzione: quale capacita' dichiarano, esattamente
#   B) il quarto d'ora dello "scatto": cosa cambia fra 10:00 e 10:45 del 16/10
#   C) l'idroelettrico in pompaggio (codice B10): assorbe l'eccesso?
#   D) bilancio per quarto d'ora: surplus della macrozona contro flussi uscenti
#
# Uscita: log\14_esito_<data_ora>.txt

import glob
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pandas as pd

CARTELLA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_ESITO = os.path.join(CARTELLA_LOG, "14_esito_" + MARCHIO + ".txt")

NOMI_ZONE = {
    "10Y1001A1001A73I": "IT Nord",
    "10Y1001A1001A70O": "IT Centro-Nord",
    "10Y1001A1001A71M": "IT Centro-Sud",
    "10Y1001A1001A788": "IT Sud",
    "10Y1001A1001A75E": "IT Sicilia",
    "10Y1001A1001A74G": "IT Sardegna",
    "10Y1001C--00096J": "IT Calabria",
}
MACRO_SUD = ["IT Sud", "IT Calabria", "IT Sicilia"]

BORDI = [
    ("SUD -> CSUD", "SUD_CSUD", "CSUD_SUD"),
    ("CALA -> SUD", "CALA_SUD", "SUD_CALA"),
    ("SICI -> CALA", "SICI_CALA", "CALA_SICI"),
    ("SUD -> GRECIA", "SUD_GR", "GR_SUD"),
    ("SICI -> MALTA", "SICI_MT", "MT_SICI"),
]


def senza_namespace(tag):
    return tag.split("}")[-1]


def figli(elemento, nome):
    return [f for f in list(elemento) if senza_namespace(f.tag) == nome]


def discendenti(radice, nome):
    return [e for e in radice.iter() if senza_namespace(e.tag) == nome]


def testo_di(elemento, nome):
    trovati = figli(elemento, nome)
    return trovati[0].text if trovati else None


def momento(testo):
    testo = testo.strip()
    if testo.endswith("Z"):
        testo = testo[:-1] + "+00:00"
    return datetime.fromisoformat(testo)


def minuti_del_passo(risoluzione):
    if risoluzione.startswith("PT"):
        resto = risoluzione[2:]
        if resto.endswith("M"):
            return int(resto[:-1])
        if resto.endswith("H"):
            return int(resto[:-1]) * 60
    return None


def serie_da_periodo(periodo, rade, tag_valore):
    intervallo = figli(periodo, "timeInterval")
    if not intervallo:
        return {}
    inizio = momento(testo_di(intervallo[0], "start"))
    fine = momento(testo_di(intervallo[0], "end"))
    minuti = minuti_del_passo(testo_di(periodo, "resolution") or "PT60M")
    if minuti is None:
        return {}
    forniti = {}
    for punto in figli(periodo, "Point"):
        posizione = testo_di(punto, "position")
        valore = testo_di(punto, tag_valore)
        if posizione is None or valore is None:
            continue
        forniti[int(posizione)] = float(valore)
    risultato = {}
    istante = inizio
    ultimo = None
    indice = 1
    while istante < fine:
        if indice in forniti:
            ultimo = forniti[indice]
            risultato[istante] = ultimo
        elif rade and ultimo is not None:
            risultato[istante] = ultimo
        istante = istante + timedelta(minutes=minuti)
        indice += 1
    return risultato


def leggi_gl(percorso):
    """Righe (zona, codice psr, istante, valore)."""
    radice = ET.parse(percorso).getroot()
    righe = []
    for serie in discendenti(radice, "TimeSeries"):
        trovati = discendenti(serie, "psrType")
        psr = (trovati[0].text or "").strip() if trovati else ""
        codice = (testo_di(serie, "outBiddingZone_Domain.mRID")
                  or testo_di(serie, "inBiddingZone_Domain.mRID") or "")
        nome = NOMI_ZONE.get(codice.strip(), codice.strip() or "?")
        rade = (testo_di(serie, "curveType") or "").upper() == "A03"
        for periodo in figli(serie, "Period"):
            for istante, valore in serie_da_periodo(periodo, rade, "quantity").items():
                righe.append((nome, psr, istante, valore))
    return righe


def leggi_quantita(percorso):
    radice = ET.parse(percorso).getroot()
    grezzi = {}
    for serie in discendenti(radice, "TimeSeries"):
        rade = (testo_di(serie, "curveType") or "").upper() == "A03"
        for periodo in figli(serie, "Period"):
            for istante, valore in serie_da_periodo(periodo, rade, "quantity").items():
                grezzi[istante] = valore
    if not grezzi:
        return pd.Series(dtype="float64")
    istanti = pd.DatetimeIndex(sorted(grezzi.keys()))
    serie = pd.Series([grezzi[i] for i in istanti], index=istanti)
    serie.index = serie.index.tz_convert("Europe/Rome")
    return serie


def leggi_prezzi_csv(percorso):
    tabella = pd.read_csv(percorso)
    tabella["istante"] = (pd.to_datetime(tabella["ora_utc"], utc=True)
                          .dt.tz_convert("Europe/Rome"))
    return tabella.pivot_table(index="istante", columns="zona",
                               values="prezzo_eur_mwh", aggfunc="last")


def lotto_piu_recente(elenco):
    marchi = set()
    for percorso in elenco:
        trovato = re.search(r"_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", os.path.basename(percorso))
        if trovato:
            marchi.add(trovato.group(1))
    if not marchi:
        return []
    ultimo = sorted(marchi)[-1]
    return [p for p in elenco if ultimo in os.path.basename(p)]


def stampa_tabella(intestazioni, righe):
    colonne = [intestazioni] + [[str(c) for c in riga] for riga in righe]
    larghezze = [max(len(riga[i]) for riga in colonne) + 2 for i in range(len(intestazioni))]
    for riga in colonne:
        print("  " + "".join(riga[i].ljust(larghezze[i]) for i in range(len(riga))))
    print()


def principale():
    print("=== AVVIO", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "===")
    print()

    file_manut = sorted(glob.glob(os.path.join(CARTELLA_LOG, "12_A78_*_[0-9].xml")))
    file_flussi = lotto_piu_recente(sorted(glob.glob(os.path.join(CARTELLA_LOG, "12_A11_*.xml"))))
    file_carico = lotto_piu_recente(sorted(glob.glob(os.path.join(CARTELLA_LOG, "10_A65_*.xml"))))
    file_gen = lotto_piu_recente(sorted(glob.glob(os.path.join(CARTELLA_LOG, "10_A75_*.xml"))))
    file_prezzi = sorted(glob.glob(os.path.join(CARTELLA_LOG, "04_prezzi_*.csv")))

    # ---- A) manutenzioni: valori esatti ------------------------------------
    print("############ A) MANUTENZIONI: VALORI ESATTI ############")
    for percorso in file_manut:
        radice = ET.parse(percorso).getroot()
        for serie in discendenti(radice, "TimeSeries"):
            entrata = testo_di(serie, "in_Domain.mRID")
            uscita = testo_di(serie, "out_Domain.mRID")
            for periodo in figli(serie, "Available_Period"):
                intervallo = figli(periodo, "timeInterval")
                inizio = momento(testo_di(intervallo[0], "start"))
                fine = momento(testo_di(intervallo[0], "end"))
                for punto in figli(periodo, "Point"):
                    print("  %s -> %s | %s -> %s UTC | disponibile: %s %s | tipo %s | risoluzione %s"
                          % (NOMI_ZONE.get(entrata, entrata), NOMI_ZONE.get(uscita, uscita),
                             inizio.strftime("%d/%m %H:%M"), fine.strftime("%d/%m %H:%M"),
                             testo_di(punto, "quantity"),
                             testo_di(serie, "quantity_Measure_Unit.name") or "",
                             testo_di(serie, "businessType"),
                             testo_di(periodo, "resolution")))
    print()

    # ---- B) lo scatto del prezzo ------------------------------------------
    print("############ B) LO SCATTO: 16/10 DALLE 10:00 ALLE 11:00 ############")
    prezzi = leggi_prezzi_csv(file_prezzi[-1])
    prezzo_sud = prezzi["IT Sud"]
    netti = {}
    for etichetta, avanti, indietro in BORDI:
        a = None
        b = None
        for percorso in file_flussi:
            base = os.path.basename(percorso)
            if ("_A11_%s_" % avanti) in base:
                a = leggi_quantita(percorso)
            if ("_A11_%s_" % indietro) in base:
                b = leggi_quantita(percorso)
        if a is None:
            continue
        if b is None:
            b = pd.Series(0.0, index=a.index)
        comune = a.index.union(b.index)
        netti[etichetta] = a.reindex(comune).fillna(0.0) - b.reindex(comune).fillna(0.0)

    righe = []
    inizio = pd.Timestamp("2026-10-16 10:00", tz="Europe/Rome")
    for passo in range(5):
        istante = inizio + timedelta(minutes=15 * passo)
        riga = [istante.strftime("%H:%M"),
                "%.2f" % prezzo_sud.get(istante, float("nan")),
                "%.0f" % netti["SUD -> CSUD"].get(istante, float("nan")),
                "%.0f" % netti["SUD -> GRECIA"].get(istante, float("nan")),
                "%.0f" % netti["CALA -> SUD"].get(istante, float("nan")),
                "%.0f" % netti["SICI -> CALA"].get(istante, float("nan"))]
        righe.append(riga)
    stampa_tabella(["ora", "prezzo Sud", "SUD->CSUD", "SUD->GRECIA", "CALA->SUD", "SICI->CALA"], righe)

    # ---- C) pompaggio ------------------------------------------------------
    print("############ C) IDROELETTRICO IN POMPAGGIO (B10) A MEZZOGIORNO ############")
    righe = []
    for giorno in ["2026-10-16", "2026-10-17"]:
        for percorso in file_gen:
            for nome_zona, psr, istante, valore in leggi_gl(percorso):
                if psr != "B10":
                    continue
                if nome_zona not in MACRO_SUD + ["IT Centro-Sud"]:
                    continue
                locale = pd.Timestamp(istante).tz_convert("Europe/Rome")
                if locale.date() != pd.Timestamp(giorno).date():
                    continue
                if not (11 <= locale.hour < 15):
                    continue
                righe.append((giorno, nome_zona, locale.strftime("%H:%M"), valore))
    riepilogo = {}
    for giorno, zona, ora, valore in righe:
        chiave = (giorno, zona)
        riepilogo.setdefault(chiave, []).append(valore)
    righe_tabella = []
    for (giorno, zona), valori in sorted(riepilogo.items()):
        righe_tabella.append([giorno, zona, len(valori), "%.0f" % min(valori), "%.0f" % max(valori)])
    stampa_tabella(["giorno", "zona", "quarti", "B10 minimo", "B10 massimo"], righe_tabella)

    # ---- D) bilancio per quarto d'ora -------------------------------------
    print("############ D) BILANCIO PER QUARTO D'ORA (16/10) ############")
    righe_carico = []
    for percorso in file_carico:
        for nome, _, istante, valore in leggi_gl(percorso):
            righe_carico.append((nome, istante, valore))
    carico = pd.DataFrame(righe_carico, columns=["zona", "istante", "mw"])
    carico = carico.pivot_table(index="istante", columns="zona", values="mw", aggfunc="sum")
    carico.index = carico.index.tz_convert("Europe/Rome")

    righe_gen = []
    for percorso in file_gen:
        for nome, psr, istante, valore in leggi_gl(percorso):
            righe_gen.append((nome, psr, istante, valore))
    gen = pd.DataFrame(righe_gen, columns=["zona", "psr", "istante", "mw"])
    gen = gen.pivot_table(index=["zona", "istante"], columns="psr", values="mw",
                          aggfunc="sum").fillna(0.0)
    totale = gen.loc[MACRO_SUD].groupby(level="istante").sum().sum(axis=1)
    totale.index = totale.index.tz_convert("Europe/Rome")
    pompaggio = pd.Series(0.0, index=totale.index)
    for psr in ("B10",):
        if psr in gen.columns:
            pezzo = gen.loc[MACRO_SUD, psr].groupby(level="istante").sum()
            pezzo.index = pezzo.index.tz_convert("Europe/Rome")
            pompaggio = pezzo.reindex(totale.index).fillna(0.0)
    surplus = totale - carico[MACRO_SUD].sum(axis=1)
    uscite = (netti["SUD -> CSUD"].reindex(surplus.index).fillna(0.0)
              + netti["SUD -> GRECIA"].reindex(surplus.index).fillna(0.0)
              + netti["SICI -> MALTA"].reindex(surplus.index).fillna(0.0))

    tabella = pd.DataFrame({"surplus": surplus, "pompaggio_B10": pompaggio,
                            "uscite": uscite, "residuo": surplus - uscite})
    righe = []
    for istante, valori in tabella.iterrows():
        if istante.date() != pd.Timestamp("2026-10-16").date():
            continue
        if not (9 <= istante.hour < 16):
            continue
        if istante.minute % 30 != 0:
            continue
        righe.append([istante.strftime("%H:%M"),
                      "%.0f" % valori["surplus"], "%.0f" % valori["pompaggio_B10"],
                      "%.0f" % valori["uscite"], "%.0f" % valori["residuo"]])
    stampa_tabella(["ora", "surplus macro", "di cui pompaggio B10", "uscite totali", "residuo"], righe)

    print("=== FINE ===")


class Doppio:
    def __init__(self, percorso, schermo):
        self.file = open(percorso, "w", encoding="utf-8")
        self.schermo = schermo

    def write(self, testo):
        self.file.write(testo)
        self.schermo.write(testo)

    def flush(self):
        self.file.flush()
        self.schermo.flush()


SCHERMO = sys.stdout
DOPPIO = Doppio(FILE_ESITO, SCHERMO)
sys.stdout = DOPPIO
try:
    principale()
except Exception:
    import traceback
    traceback.print_exc(file=DOPPIO)
finally:
    DOPPIO.flush()
    DOPPIO.file.close()
    sys.stdout = SCHERMO
