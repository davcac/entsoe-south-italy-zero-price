# 11_diagnosi.py
#
# Legge i file GIA' scaricati (nessun volume da montare) e prova a rispondere
# alla domanda: perche' il 16/10 a mezzogiorno il Sud e' andato a 0 e il 17 no?
#
# File usati, dalla cartella log\ :
#   04_prezzi_*.csv    prezzi day-ahead delle 7 zone italiane (script 04)
#   10_A65_*.xml       carico (domanda) per zona                 (script 10)
#   10_A75_*.xml       generazione per tipo di impianto          (script 10)
#   10_A44_*.xml       prezzi day-ahead dei paesi vicini         (script 10)
#
# L'idea: una zona va a prezzo 0 quando
#       surplus = generazione interna - domanda interna
# supera quello che la rete riesce a esportare verso le zone vicine.
# Qui si misura il surplus nei due giorni e con quali fonti e' fatto.
#
# Uscita: log\11_esito_<data_ora>.txt

import glob
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pandas as pd

CARTELLA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_ESITO = os.path.join(CARTELLA_LOG, "11_esito_" + MARCHIO + ".txt")

# codici EIC delle 7 zone italiane
NOMI_ZONE = {
    "10Y1001A1001A73I": "IT Nord",
    "10Y1001A1001A70O": "IT Centro-Nord",
    "10Y1001A1001A71M": "IT Centro-Sud",
    "10Y1001A1001A788": "IT Sud",
    "10Y1001A1001A75E": "IT Sicilia",
    "10Y1001A1001A74G": "IT Sardegna",
    "10Y1001C--00096J": "IT Calabria",
}

ZONE = ["IT Nord", "IT Centro-Nord", "IT Centro-Sud", "IT Sud",
        "IT Sicilia", "IT Calabria", "IT Sardegna"]

MACRO_SUD = ["IT Sud", "IT Calabria", "IT Sicilia"]

# a quale fonte appartiene ogni codice psrType
FONTE_DI = {
    "B16": "solare",
    "B18": "eolico", "B19": "eolico",
    "B10": "idro", "B11": "idro", "B12": "idro",
    "B04": "gas",
    "B01": "altro", "B02": "altro", "B03": "altro", "B05": "altro",
    "B06": "altro", "B07": "altro", "B08": "altro", "B09": "altro",
    "B13": "altro", "B14": "altro", "B15": "altro", "B17": "altro",
    "B20": "altro", "B25": "altro",
}
FONTI = ["solare", "eolico", "idro", "gas", "altro"]


# ---------------------------------------------------------------------------
# lettura degli XML
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
    if risoluzione.startswith("P") and risoluzione.endswith("D"):
        return int(risoluzione[1:-1]) * 24 * 60
    return None


def serie_da_periodo(periodo, rade, tag_valore):
    """Da un <Period> alle coppie (istante UTC, valore).

    Con curveType A03 le posizioni omesse ripetono il valore precedente.
    """
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
    """GL_MarketDocument (A65 carico, A75 generazione per tipo).

    Restituisce righe (nome zona, psr, istante UTC, valore).
    """
    radice = ET.parse(percorso).getroot()
    righe = []
    for serie in discendenti(radice, "TimeSeries"):
        # psrType sta dentro <MktPSRType>, non e' figlio diretto della serie
        trovati_psr = discendenti(serie, "psrType")
        psr = (trovati_psr[0].text or "").strip() if trovati_psr else ""
        codice = (testo_di(serie, "outBiddingZone_Domain.mRID")
                  or testo_di(serie, "inBiddingZone_Domain.mRID") or "")
        nome = NOMI_ZONE.get(codice.strip(), codice.strip() or "?")
        rade = (testo_di(serie, "curveType") or "").upper() == "A03"
        for periodo in figli(serie, "Period"):
            for istante, valore in serie_da_periodo(periodo, rade, "quantity").items():
                righe.append((nome, psr, istante, valore))
    return righe


def leggi_prezzi_xml(percorso):
    """Publication_MarketDocument (A44). Restituisce una Series {istante UTC: prezzo}."""
    radice = ET.parse(percorso).getroot()
    grezzi = {}
    for serie in discendenti(radice, "TimeSeries"):
        rade = (testo_di(serie, "curveType") or "").upper() == "A03"
        for periodo in figli(serie, "Period"):
            for istante, valore in serie_da_periodo(periodo, rade, "price.amount").items():
                grezzi[istante] = valore          # fra piu' versioni vince l'ultima
    if not grezzi:
        return pd.Series(dtype="float64")
    istanti = pd.DatetimeIndex(sorted(grezzi.keys()))
    return pd.Series([grezzi[i] for i in istanti], index=istanti)


def lotto_piu_recente(elenco):
    """Fra i file con data nel nome tiene solo quelli del lotto piu' recente."""
    marchi = set()
    for percorso in elenco:
        trovato = re.search(r"_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.xml$",
                            os.path.basename(percorso))
        if trovato:
            marchi.add(trovato.group(1))
    if not marchi:
        return []
    ultimo = sorted(marchi)[-1]
    return [p for p in elenco if ultimo in os.path.basename(p)]


# ---------------------------------------------------------------------------
# costruzione delle tabelle
# ---------------------------------------------------------------------------

def a_italiana(indice):
    """Indice UTC -> indice in ora italiana."""
    indice = pd.DatetimeIndex(indice)
    if indice.tz is None:
        indice = indice.tz_localize("UTC")
    return indice.tz_convert("Europe/Rome")


def carica_carico(elenco_file):
    righe = []
    for percorso in elenco_file:
        for nome, _, istante, valore in leggi_gl(percorso):
            righe.append((nome, istante, valore))
    tabella = pd.DataFrame(righe, columns=["zona", "istante", "mw"])
    tabella = tabella.pivot_table(index="istante", columns="zona",
                                  values="mw", aggfunc="sum")
    tabella.index = a_italiana(tabella.index)
    return tabella


def carica_generazione(elenco_file):
    righe = []
    for percorso in elenco_file:
        for nome, psr, istante, valore in leggi_gl(percorso):
            righe.append((nome, FONTE_DI.get(psr, "altro"), istante, valore))
    tabella = pd.DataFrame(righe, columns=["zona", "fonte", "istante", "mw"])
    tabella = tabella.pivot_table(index=["zona", "istante"], columns="fonte",
                                  values="mw", aggfunc="sum")
    tabella = tabella.reindex(columns=FONTI).fillna(0.0)
    return tabella


def carica_prezzi_csv(percorso):
    tabella = pd.read_csv(percorso)
    tabella["istante"] = pd.to_datetime(tabella["ora_utc"], utc=True)
    tabella = tabella.pivot_table(index="istante", columns="zona",
                                  values="prezzo_eur_mwh", aggfunc="last")
    tabella.index = a_italiana(tabella.index)
    return tabella


# ---------------------------------------------------------------------------
# stampa
# ---------------------------------------------------------------------------

def stampa_tabella(intestazioni, righe):
    colonne = [intestazioni] + [[str(c) for c in riga] for riga in righe]
    larghezze = [max(len(riga[i]) for riga in colonne) + 2
                 for i in range(len(intestazioni))]
    for riga in colonne:
        print("  " + "".join(riga[i].ljust(larghezze[i]) for i in range(len(riga))))
    print()


def medie(tabella, inizio, fine):
    """Media su una finestra oraria (ora italiana) del giorno indicato."""
    maschera = ((tabella.index.date == inizio.date())
                & (tabella.index.hour >= inizio.hour)
                & (tabella.index.hour < fine.hour))
    return tabella[maschera]


def riga_macro(carico, generazione, elenco_zone, istante_inizio, istante_fine):
    """Totale carico, generazione per fonte e surplus su piu' zone."""
    carico_macro = carico[elenco_zone].sum(axis=1)
    gen_macro = generazione.loc[elenco_zone].groupby(level="istante").sum()
    gen_macro = gen_macro.reindex(carico.index)
    totale = gen_macro.sum(axis=1)
    surplus = totale - carico_macro
    return carico_macro, gen_macro, totale, surplus


def principale():
    print("=== AVVIO", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "===")
    print("Resoconto:", FILE_ESITO)
    print()

    # ---- file di input -----------------------------------------------------
    file_carico = lotto_piu_recente(sorted(glob.glob(os.path.join(CARTELLA_LOG, "10_A65_*.xml"))))
    file_gen = lotto_piu_recente(sorted(glob.glob(os.path.join(CARTELLA_LOG, "10_A75_*.xml"))))
    file_vicini = lotto_piu_recente(sorted(glob.glob(os.path.join(CARTELLA_LOG, "10_A44_*.xml"))))
    file_prezzi = sorted(glob.glob(os.path.join(CARTELLA_LOG, "04_prezzi_*.csv")))
    if not (file_carico and file_gen and file_prezzi):
        print("Mancano dei file (10_A65_*, 10_A75_* o 04_prezzi_*). Interrompo.")
        return
    print("Carico  : %d file, lotto %s" % (len(file_carico), os.path.basename(file_carico[0])[-23:-4]))
    print("Generazi: %d file" % len(file_gen))
    print("Vicini  : %d file" % len(file_vicini))
    print("Prezzi  : %s" % os.path.basename(file_prezzi[-1]))
    print()

    carico = carica_carico(file_carico)
    generazione = carica_generazione(file_gen)
    prezzi = carica_prezzi_csv(file_prezzi[-1])
    print("Finestra dei dati: %s -> %s (ora italiana)"
          % (carico.index[0].strftime("%d/%m %H:%M"), carico.index[-1].strftime("%d/%m %H:%M")))
    print("Passi da 15 minuti: %d | zone di carico: %d" % (len(carico), len(carico.columns)))
    print("Colonne dei prezzi:", list(prezzi.columns))
    print()

    # ---- 1) controllo di coerenza con i totali nazionali -------------------
    print("############ 1) CONTROLLO: totali nazionali a mezzogiorno ############")
    print("(somma delle 7 zone; le cifre di riferimento vengono da energy-charts)")
    intestazioni = ["giorno", "solare", "eolico", "idro", "gas", "tot gen", "carico"]
    righe = []
    for giorno in ["2026-10-16", "2026-10-17", "2026-10-18"]:
        inizio = pd.Timestamp(giorno + " 11:00", tz="Europe/Rome")
        fine = pd.Timestamp(giorno + " 15:00", tz="Europe/Rome")
        gen_finestra = generazione.groupby(level="istante").sum().reindex(carico.index)
        carico_finestra = carico.sum(axis=1)
        valori = [giorno]
        for fonte in ["solare", "eolico", "idro", "gas"]:
            valori.append("%.0f" % medie(gen_finestra[fonte], inizio, fine).mean())
        valori.append("%.0f" % medie(gen_finestra.sum(axis=1), inizio, fine).mean())
        valori.append("%.0f" % medie(carico_finestra, inizio, fine).mean())
        righe.append(valori)
    stampa_tabella(intestazioni, righe)

    # ---- 2) surplus per zona a mezzogiorno, 16 contro 17 -------------------
    print("############ 2) SURPLUS A MEZZOGIORNO (11:00-15:00) ############")
    print("surplus = generazione interna - domanda interna  [MW]")
    for giorno in ["2026-10-16", "2026-10-17"]:
        print("--- %s ---" % giorno)
        inizio = pd.Timestamp(giorno + " 11:00", tz="Europe/Rome")
        fine = pd.Timestamp(giorno + " 15:00", tz="Europe/Rome")
        gen_finestra = generazione.groupby(level="istante").sum().reindex(carico.index)
        intestazioni = ["zona", "carico", "solare", "eolico", "idro", "gas", "altro",
                        "tot gen", "surplus", "prezzo"]
        righe = []
        for zona in ZONE:
            carico_zona = carico[zona]
            carico_medio = medie(carico_zona, inizio, fine).mean()
            sorgenti = []
            for fonte in FONTI:
                serie = generazione.loc[zona, fonte]
                sorgenti.append(medie(serie, inizio, fine).mean())
            totale = sum(sorgenti)
            surplus = totale - carico_medio
            prezzo = medie(prezzi[zona], inizio, fine).mean()
            righe.append([zona, "%.0f" % carico_medio] + ["%.0f" % s for s in sorgenti]
                         + ["%.0f" % totale, "%+.0f" % surplus, "%.0f" % prezzo])
        # macrozona Sud + Calabria + Sicilia
        carico_macro, gen_macro, totale_macro, surplus_macro = riga_macro(
            carico, generazione, MACRO_SUD, inizio, fine)
        sorgenti = [medie(gen_macro[fonte], inizio, fine).mean() for fonte in FONTI]
        righe.append(["SUD+CALA+SIC", "%.0f" % medie(carico_macro, inizio, fine).mean()]
                     + ["%.0f" % s for s in sorgenti]
                     + ["%.0f" % medie(totale_macro, inizio, fine).mean(),
                        "%+.0f" % medie(surplus_macro, inizio, fine).mean(),
                        "%.0f" % medie(prezzi[MACRO_SUD], inizio, fine).mean(axis=1).mean()])
        stampa_tabella(intestazioni, righe)

    # ---- 3) quarto d'ora per 15 minuti, nel cuore del fenomeno -------------
    print("############ 3) QUARTO D'ORA PER QUARTO D'ORA, macrozona SUD ############")
    carico_macro, gen_macro, totale_macro, surplus_macro = riga_macro(
        carico, generazione, MACRO_SUD, None, None)
    for giorno in ["2026-10-16", "2026-10-17"]:
        print("--- %s (Sud + Calabria + Sicilia) ---" % giorno)
        inizio = pd.Timestamp(giorno + " 09:00", tz="Europe/Rome")
        fine = pd.Timestamp(giorno + " 16:00", tz="Europe/Rome")
        maschera = (surplus_macro.index.date == inizio.date()) & (surplus_macro.index.hour >= 9) & (surplus_macro.index.hour < 16)
        intestazioni = ["ora", "solare", "eolico", "idro+gas", "tot gen", "carico", "surplus", "prezzo Sud"]
        righe = []
        for istante in surplus_macro.index[maschera]:
            if istante.minute % 30 != 0:
                continue
            val_solare = generazione.loc[MACRO_SUD, "solare"].groupby(level="istante").sum().get(istante, 0.0)
            val_eolico = generazione.loc[MACRO_SUD, "eolico"].groupby(level="istante").sum().get(istante, 0.0)
            val_idrogas = generazione.loc[MACRO_SUD, ["idro", "gas", "altro"]].groupby(level="istante").sum().sum(axis=1).get(istante, 0.0)
            carico_macro_val = carico[MACRO_SUD].sum(axis=1).get(istante)
            totale_val = val_solare + val_eolico + val_idrogas
            surplus_val = totale_val - carico_macro_val
            prezzo = prezzi["IT Sud"].get(istante, float("nan"))
            righe.append([istante.strftime("%d/%m %H:%M"), "%.0f" % val_solare,
                          "%.0f" % val_eolico, "%.0f" % val_idrogas,
                          "%.0f" % totale_val, "%.0f" % carico_macro_val,
                          "%+.0f" % surplus_val, "%.2f" % prezzo])
        stampa_tabella(intestazioni, righe)

    # ---- 3) la soglia: surplus contro prezzo ------------------------------
    print("############ 4) LA SOGLIA: surplus della zona Sud contro prezzo ############")
    print("(tutti i quarti d'ora dei 4 giorni; surplus della sola zona IT Sud)")
    gen_sud = generazione.loc["IT Sud"]
    surplus_sud = gen_sud.sum(axis=1) - carico["IT Sud"]
    prezzo_sud = prezzi["IT Sud"]
    # i prezzi coprono solo 16-18/10: tengo i quarti d'ora presenti in entrambi
    comuni = surplus_sud.index.intersection(prezzo_sud.index)
    print("  quarti d'ora confrontabili (surplus e prezzo insieme): %d" % len(comuni))
    surplus_sud = surplus_sud.reindex(comuni)
    prezzo_sud = prezzo_sud.reindex(comuni)
    classi = [(-10**9, 0, "surplus < 0 (deficit)"),
              (0, 2000, "0 - 2.000"),
              (2000, 4000, "2.000 - 4.000"),
              (4000, 6000, "4.000 - 6.000"),
              (6000, 8000, "6.000 - 8.000"),
              (8000, 10**9, "> 8.000")]
    intestazioni = ["classe di surplus [MW]", "quarti", "prezzo medio", "prezzo min", "prezzo max"]
    righe = []
    for basso, alto, etichetta in classi:
        maschera = (surplus_sud >= basso) & (surplus_sud < alto)
        if maschera.sum() == 0:
            righe.append([etichetta, "0", "-", "-", "-"])
            continue
        p = prezzo_sud[maschera]
        righe.append([etichetta, "%d" % maschera.sum(), "%.2f" % p.mean(),
                      "%.2f" % p.min(), "%.2f" % p.max()])
    stampa_tabella(intestazioni, righe)

    print("Piu' precisamente, sulla zona IT Sud:")
    zero = prezzo_sud[prezzo_sud < 1.0]
    print("  quarti d'ora con prezzo < 1 EUR/MWh : %d" % len(zero))
    if len(zero):
        surplus_zero = surplus_sud[prezzo_sud < 1.0]
        print("  il loro surplus va da %.0f a %.0f MW" % (surplus_zero.min(), surplus_zero.max()))
    print("  surplus massimo osservato il 16/10: %.0f MW" % surplus_sud[surplus_sud.index.date == pd.Timestamp("2026-10-16").date()].max())
    print("  surplus massimo osservato il 17/10: %.0f MW" % surplus_sud[surplus_sud.index.date == pd.Timestamp("2026-10-17").date()].max())
    print()

    print("Poveri di prezzo per zona (quarti d'ora con prezzo < 1 EUR/MWh):")
    for zona in ZONE:
        quanti = int((prezzi[zona] < 1.0).sum())
        print("  %-16s %d" % (zona, quanti))
    print()
    print("Quarti d'ora al prezzo di 400,00 EUR/MWh esatti (possibile limite di mercato):")
    for zona in ZONE:
        quanti = int((prezzi[zona] > 399.99).sum())
        print("  %-16s %d" % (zona, quanti))
    print()

    # ---- 4) prezzi dei paesi vicini ---------------------------------------
    print("############ 5) PREZZI DEI VICINI A MEZZOGIORNO (11:00-15:00) ############")
    intestazioni = ["giorno", "IT Sud", "Grecia", "Francia", "Austria", "Slovenia", "Svizzera", "Montenegro"]
    righe = []
    nomi_vicini = {"GR": "Grecia", "FR": "Francia", "AT": "Austria",
                   "SI": "Slovenia", "CH": "Svizzera", "ME": "Montenegro"}
    vicini = {}
    for percorso in file_vicini:
        breve = os.path.basename(percorso).split("_")[2]
        serie = leggi_prezzi_xml(percorso)
        if len(serie):
            serie.index = a_italiana(serie.index)
            vicini[nomi_vicini.get(breve, breve)] = serie
    for giorno in ["2026-10-16", "2026-10-17", "2026-10-18"]:
        inizio = pd.Timestamp(giorno + " 11:00", tz="Europe/Rome")
        fine = pd.Timestamp(giorno + " 15:00", tz="Europe/Rome")
        valori = [giorno, "%.2f" % medie(prezzi["IT Sud"], inizio, fine).mean()]
        for nome in ["Grecia", "Francia", "Austria", "Slovenia", "Svizzera", "Montenegro"]:
            serie = vicini.get(nome)
            if serie is None or len(serie) == 0:
                valori.append("-")
            else:
                valori.append("%.2f" % medie(serie, inizio, fine).mean())
        righe.append(valori)
    stampa_tabella(intestazioni, righe)

    print("=== FINE ===")


# ---------------------------------------------------------------------------
# avvio
# ---------------------------------------------------------------------------

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
