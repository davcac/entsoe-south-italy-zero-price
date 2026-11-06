# 13_flussi.py
#
# Legge i flussi fisici reali (A11) e le manutenzioni (A78) gia' scaricati e li
# mette insieme a carico (A65), generazione (A75) e prezzi. Nessun volume.
#
# Domande:
#   1) cosa dice il file manutenzioni della rete?
#   2) quanto passa davvero su ogni confine a mezzogiorno, nei due giorni?
#   3) a che livello si ferma il corridoio Sud -> Centro-Sud (capacita' reale)?
#   4) il flusso sul confine Sud <-> Calabria sta al valore dichiarato (600 MW)?
#   5) il bilancio torna?  surplus del Sud = flussi uscenti?
#
# Uscita: log\13_esito_<data_ora>.txt

import glob
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pandas as pd

CARTELLA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_ESITO = os.path.join(CARTELLA_LOG, "13_esito_" + MARCHIO + ".txt")

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
FONTE_DI = {
    "B16": "solare", "B18": "eolico", "B19": "eolico",
    "B10": "idro", "B11": "idro", "B12": "idro", "B04": "gas",
}
FONTI = ["solare", "eolico", "idro", "gas", "altro"]

# etichetta, file del verso positivo, file del verso opposto
BORDI = [
    ("SUD -> CSUD", "SUD_CSUD", "CSUD_SUD"),
    ("CALA -> SUD", "CALA_SUD", "SUD_CALA"),
    ("SICI -> CALA", "SICI_CALA", "CALA_SICI"),
    ("SUD -> GRECIA", "SUD_GR", "GR_SUD"),
    ("SICI -> MALTA", "SICI_MT", "MT_SICI"),
]


# ---------------------------------------------------------------------------
# lettura XML
# ---------------------------------------------------------------------------

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
    """Da un <Period> alle coppie (istante, valore), con riempimento in avanti."""
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
    """GL_MarketDocument (A65 carico / A75 generazione). Righe (zona, fonte, istante, mw)."""
    radice = ET.parse(percorso).getroot()
    righe = []
    for serie in discendenti(radice, "TimeSeries"):
        trovati = discendenti(serie, "psrType")
        psr = (trovati[0].text or "").strip() if trovati else ""
        fonte = FONTE_DI.get(psr, "altro")
        codice = (testo_di(serie, "outBiddingZone_Domain.mRID")
                  or testo_di(serie, "inBiddingZone_Domain.mRID") or "")
        nome = NOMI_ZONE.get(codice.strip(), codice.strip() or "?")
        rade = (testo_di(serie, "curveType") or "").upper() == "A03"
        for periodo in figli(serie, "Period"):
            for istante, valore in serie_da_periodo(periodo, rade, "quantity").items():
                righe.append((nome, fonte, istante, valore))
    return righe


def leggi_quantita(percorso):
    """A11/A44: una Series di quantita' (MW o EUR/MWh) indicizzata in ora italiana."""
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


def finestra(serie, giorno, ora_inizio, ora_fine):
    maschera = ((serie.index.date == pd.Timestamp(giorno).date())
                & (serie.index.hour >= ora_inizio) & (serie.index.hour < ora_fine))
    return serie[maschera]


def valore_medio(serie, giorno):
    valori = finestra(serie, giorno, 11, 15)
    return valori.mean() if len(valori) else float("nan")


# ---------------------------------------------------------------------------

def principale():
    print("=== AVVIO", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "===")
    print("Resoconto:", FILE_ESITO)
    print()

    file_flussi = lotto_piu_recente(sorted(glob.glob(os.path.join(CARTELLA_LOG, "12_A11_*.xml"))))
    file_manut = sorted(glob.glob(os.path.join(CARTELLA_LOG, "12_A78_*_[0-9].xml")))
    file_carico = lotto_piu_recente(sorted(glob.glob(os.path.join(CARTELLA_LOG, "10_A65_*.xml"))))
    file_gen = lotto_piu_recente(sorted(glob.glob(os.path.join(CARTELLA_LOG, "10_A75_*.xml"))))
    file_prezzi = sorted(glob.glob(os.path.join(CARTELLA_LOG, "04_prezzi_*.csv")))
    if not (file_flussi and file_carico and file_gen and file_prezzi):
        print("Mancano dei file. Interrompo.")
        return
    print("File: %d flussi, %d manutenzioni, %d carico, %d generazione, %d prezzi"
          % (len(file_flussi), len(file_manut), len(file_carico), len(file_gen), len(file_prezzi)))
    print()

    # ---- 1) manutenzioni ---------------------------------------------------
    print("############ 1) MANUTENZIONI DELLA RETE (A78) ############")
    for percorso in file_manut:
        radice = ET.parse(percorso).getroot()
        print("  documento %s | creato il %s"
              % (os.path.basename(percorso), testo_di(radice, "createdDateTime")))
        for serie in discendenti(radice, "TimeSeries"):
            entrata = testo_di(serie, "in_Domain.mRID")
            uscita = testo_di(serie, "out_Domain.mRID")
            print("    confine: %s <-> %s | tipo (businessType): %s"
                  % (NOMI_ZONE.get(entrata, entrata), NOMI_ZONE.get(uscita, uscita),
                     testo_di(serie, "businessType")))
            for periodo in figli(serie, "Available_Period"):
                intervallo = figli(periodo, "timeInterval")
                if intervallo:
                    inizio = momento(testo_di(intervallo[0], "start"))
                    fine = momento(testo_di(intervallo[0], "end"))
                    print("    periodo dichiarato: %s -> %s (UTC)"
                          % (inizio.strftime("%d/%m %H:%M"), fine.strftime("%d/%m %H:%M")))
                for punto in figli(periodo, "Point"):
                    print("    capacita' disponibile dichiarata: %s %s"
                          % (testo_di(punto, "quantity"),
                             testo_di(serie, "quantity_Measure_Unit.name") or ""))
    print()

    # ---- 2) flussi netti ---------------------------------------------------
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
            print("  (nessun file per il confine %s)" % etichetta)
            continue
        if b is None:
            b = pd.Series(0.0, index=a.index)
        comune = a.index.union(b.index)
        netti[etichetta] = a.reindex(comune).fillna(0.0) - b.reindex(comune).fillna(0.0)
    print()

    print("############ 2) FLUSSI FISICI REALI A MEZZOGIORNO (11:00-15:00) ############")
    print("positivo = verso l'etichetta (SUD -> CSUD significa verso il Centro-Sud)")
    intestazioni = ["confine", "giorno", "medio", "minimo", "massimo"]
    righe = []
    for etichetta, _, _ in BORDI:
        if etichetta not in netti:
            continue
        for giorno in ["2026-10-16", "2026-10-17"]:
            valori = finestra(netti[etichetta], giorno, 11, 15)
            if len(valori) == 0:
                continue
            righe.append([etichetta, giorno[5:], "%.0f" % valori.mean(),
                          "%.0f" % valori.min(), "%.0f" % valori.max()])
    stampa_tabella(intestazioni, righe)

    # ---- carico, generazione, surplus --------------------------------------
    righe_carico = []
    for percorso in file_carico:
        for nome, _, istante, valore in leggi_gl(percorso):
            righe_carico.append((nome, istante, valore))
    carico = pd.DataFrame(righe_carico, columns=["zona", "istante", "mw"])
    carico = carico.pivot_table(index="istante", columns="zona", values="mw", aggfunc="sum")
    carico.index = carico.index.tz_convert("Europe/Rome")

    righe_gen = []
    for percorso in file_gen:
        for nome, fonte, istante, valore in leggi_gl(percorso):
            righe_gen.append((nome, fonte, istante, valore))
    gen = pd.DataFrame(righe_gen, columns=["zona", "fonte", "istante", "mw"])
    gen = gen.pivot_table(index=["zona", "istante"], columns="fonte",
                          values="mw", aggfunc="sum").reindex(columns=FONTI).fillna(0.0)

    gen_macro = gen.loc[MACRO_SUD].groupby(level="istante").sum().reindex(carico.index)
    surplus_macro = gen_macro.sum(axis=1) - carico[MACRO_SUD].sum(axis=1)
    prezzi = leggi_prezzi_csv(file_prezzi[-1])
    prezzo_sud = prezzi["IT Sud"]

    # ---- 3) il corridoio ---------------------------------------------------
    print("############ 3) IL CORRIDOIO SUD -> CSUD: DOVE SI FERMA ############")
    corridoio = netti.get("SUD -> CSUD")
    if corridoio is not None:
        print("  massimo flusso SUD -> CSUD su tutti i 4 giorni: %.0f MW il %s"
              % (corridoio.max(), corridoio.idxmax().strftime("%d/%m %H:%M")))
        print("  flusso medio sui 4 giorni: %.0f MW" % corridoio.mean())
    print()

    # ---- 4) il tetto: surplus contro flusso --------------------------------
    print("############ 4) IL TETTO: IL SURPLUS CRESCE, IL FLUSSO NO ############")
    print("(i 12 quarti d'ora con il surplus piu' alto dei 4 giorni)")
    intestazioni = ["quando", "surplus macro", "SUD->CSUD", "CALA->SUD", "SICI->CALA",
                    "SUD->GR", "SICI->MT", "prezzo Sud"]
    righe = []
    for istante in surplus_macro.sort_values(ascending=False).head(12).index:
        riga = [istante.strftime("%d/%m %H:%M"), "%.0f" % surplus_macro.get(istante, float("nan"))]
        for etichetta, _, _ in BORDI:
            if etichetta not in netti:
                riga.append("-")
                continue
            riga.append("%.0f" % netti[etichetta].get(istante, float("nan")))
        riga.append("%.2f" % prezzo_sud.get(istante, float("nan")))
        righe.append(riga)
    stampa_tabella(intestazioni, righe)

    # ---- 4b) il corridoio nei quarti d'ora a prezzo zero -------------------
    print("############ 4b) IL CORRIDOIO NEI QUARTI D'ORA A PREZZO ~0 ############")
    zero = prezzo_sud[prezzo_sud < 1.0]
    print("  quarti d'ora a prezzo < 1 EUR/MWh sulla zona IT Sud: %d" % len(zero))
    if len(zero):
        print("  dal %s al %s (ora italiana)"
              % (zero.index.min().strftime("%d/%m %H:%M"), zero.index.max().strftime("%d/%m %H:%M")))
        corridoio = netti.get("SUD -> CSUD")
        if corridoio is not None:
            valori = corridoio.reindex(corridoio.index.intersection(zero.index))
            print("  flusso SUD -> CSUD in quei quarti: medio %.0f | minimo %.0f | massimo %.0f MW"
                  % (valori.mean(), valori.min(), valori.max()))
        valori_surplus = surplus_macro.reindex(surplus_macro.index.intersection(zero.index))
        print("  surplus della macrozona in quei quarti: medio %.0f | massimo %.0f MW"
              % (valori_surplus.mean(), valori_surplus.max()))
    if "SUD -> CSUD" in netti:
        corridoio = netti["SUD -> CSUD"]
        massimo = corridoio.max()
        print("  massimo flusso SUD -> CSUD su tutti i 4 giorni: %.0f MW il %s"
              % (massimo, corridoio.idxmax().strftime("%d/%m %H:%M")))
    print()

    # ---- 5) il confine Sud <-> Calabria e i 600 MW -------------------------
    print("############ 5) CONFINE SUD <-> CALABRIA E I 600 MW DICHIARATI ############")
    if "CALA -> SUD" in netti:
        serie = netti["CALA -> SUD"]
        print("  flusso netto CALA -> SUD: massimo %.0f MW (%s) | medio %.0f MW"
              % (serie.max(), serie.idxmax().strftime("%d/%m %H:%M"), serie.mean()))
        for giorno in ["2026-10-16", "2026-10-17"]:
            valori = finestra(serie, giorno, 11, 15)
            print("    %s 11:00-15:00: medio %.0f | massimo %.0f MW"
                  % (giorno, valori.mean(), valori.max()))
    if "SICI -> CALA" in netti:
        serie = netti["SICI -> CALA"]
        print("  flusso netto SICI -> CALA: massimo %.0f MW | medio %.0f MW"
              % (serie.max(), serie.mean()))
    print()

    # ---- 6) il bilancio torna? --------------------------------------------
    print("############ 6) BILANCIO: surplus della macrozona contro flussi uscenti ############")
    print("la macrozona Sud+Calabria+Sicilia esce solo da: SUD->CSUD, SUD->GRECIA, SICI->MALTA")
    intestazioni = ["giorno", "surplus macro", "SUD->CSUD", "SUD->GRECIA", "SICI->MALTA",
                    "uscite totali", "differenza"]
    righe = []
    for giorno in ["2026-10-16", "2026-10-17", "2026-10-18"]:
        surplus = valore_medio(surplus_macro, giorno)
        valori = {}
        for etichetta in ["SUD -> CSUD", "SUD -> GRECIA", "SICI -> MALTA"]:
            valori[etichetta] = valore_medio(netti[etichetta], giorno) if etichetta in netti else float("nan")
        uscite = sum(v for v in valori.values() if v == v)
        righe.append([giorno, "%.0f" % surplus,
                      "%.0f" % valori["SUD -> CSUD"],
                      "%.0f" % valori["SUD -> GRECIA"],
                      "%.0f" % valori["SICI -> MALTA"],
                      "%.0f" % uscite, "%.0f" % (surplus - uscite)])
    stampa_tabella(intestazioni, righe)

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
