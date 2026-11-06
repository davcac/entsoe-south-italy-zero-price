# 15_grafici.py
#
# Solo grafici. Nessuna chiave da montare: legge i file gia' salvati in log
# (prezzi, carico A65, generazione A75, flussi A11).
#
# Se in log c'e' anche un file 16_limiti_transito_*.csv (prodotto dallo script
# 16, che scarica i tetti di transito dichiarati da Terna), il pannello 2
# disegna anche il TETTO del corridoio Sud -> Centro-Sud come linea a scalini
# sopra il flusso fisico. E' il confronto che spiega il buco di prezzo: quando
# il flusso tocca il tetto, il mercato separa i prezzi.
# Se quel file non c'e', il grafico si fa lo stesso (senza linea del tetto).
#
# Tre pannelli con lo stesso asse dei tempi (16-18/10):
#   1) macrozona Sud (Sud + Calabria + Sicilia): generazione impilata e carico
#   2) surplus della macrozona contro il flusso verso il Centro-Sud
#   3) prezzo Sud contro prezzo Centro-Sud
# La banda grigia segna i quarti d'ora in cui il prezzo del Sud e' a zero.
#
# Uscita: log\15_grafici_<data_ora>.png  e  log\15_esito_<data_ora>.txt
# Si lancia in IDLE con F5.

import glob
import os
import re
import sys
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

CARTELLA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_ESITO = os.path.join(CARTELLA_LOG, "15_esito_" + MARCHIO + ".txt")

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
    ("SUD -> GRECIA", "SUD_GR", "GR_SUD"),
    ("SICI -> MALTA", "SICI_MT", "MT_SICI"),
    ("CALA -> SUD", "CALA_SUD", "SUD_CALA"),
    ("SICI -> CALA", "SICI_CALA", "CALA_SICI"),
]

FINESTRA_INIZIO = pd.Timestamp("2026-10-16 00:00", tz="Europe/Rome")
FINESTRA_FINE = pd.Timestamp("2026-10-19 00:00", tz="Europe/Rome")

FONTI = ["solare", "eolico", "resto"]
COLORI_FONTI = {"solare": "#f2c14e", "eolico": "#4c9f70", "resto": "#8d9db6"}
COLORE_TETTO = "#d35400"


# ---------------------------------------------------------------------------
# lettura dei file
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
    """Carico (A65) o generazione (A75): righe (codice_eic, psr, istante, mw)."""
    radice = ET.parse(percorso).getroot()
    righe = []
    for serie in discendenti(radice, "TimeSeries"):
        trovati = discendenti(serie, "psrType")
        psr = (trovati[0].text or "").strip() if trovati else ""
        codice = (testo_di(serie, "outBiddingZone_Domain.mRID")
                  or testo_di(serie, "inBiddingZone_Domain.mRID") or "").strip()
        rade = (testo_di(serie, "curveType") or "").upper() == "A03"
        for periodo in figli(serie, "Period"):
            for istante, valore in serie_da_periodo(periodo, rade, "quantity").items():
                righe.append((codice, psr, istante, valore))
    return righe


def leggi_quantita(percorso):
    """Flussi A11: una Series di MW indicizzata in ora italiana."""
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


def leggi_limiti(percorso, nome_serie):
    """Tetto di transito dal file dello script 16 (16_limiti_transito_*.csv).

    Il file ha una riga per valore: serie, data_ora, zona_da, zona_a, MW.
    Qui teniamo una sola serie (per esempio "limite_definitivo") e la
    indicizziamo in ora italiana, come tutti gli altri dati del grafico.
    """
    tabella = pd.read_csv(percorso)
    tabella = tabella[tabella["serie"] == nome_serie]
    if tabella.empty:
        return pd.Series(dtype="float64")
    quando = pd.to_datetime(tabella["data_ora"], format="%Y-%m-%d %H:%M")
    serie = pd.Series(tabella["valore_MW"].values, index=quando)
    serie = serie[~serie.index.duplicated(keep="last")].sort_index()
    serie.index = serie.index.tz_localize("Europe/Rome")
    return serie


def lotto_piu_recente(elenco):
    marchi = set()
    for percorso in elenco:
        trovato = re.search(r"_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})",
                            os.path.basename(percorso))
        if trovato:
            marchi.add(trovato.group(1))
    if not marchi:
        return []
    ultimo = sorted(marchi)[-1]
    return [p for p in elenco if ultimo in os.path.basename(p)]


# ---------------------------------------------------------------------------
# utilita'
# ---------------------------------------------------------------------------

def fetta_fonte(psr):
    if psr == "B16":
        return "solare"
    if psr in ("B18", "B19"):
        return "eolico"
    return "resto"


def senza_fuso(serie):
    copia = serie.copy()
    copia.index = copia.index.tz_localize(None)
    return copia


def tratti_veri(maschera):
    """(inizio, fine) dei tratti consecutivi in cui la maschera e' vera."""
    elenco = []
    inizio = None
    precedente = None
    for istante, vero in maschera.items():
        if vero and inizio is None:
            inizio = istante
        if (not vero) and inizio is not None:
            elenco.append((inizio, precedente))
            inizio = None
        precedente = istante
    if inizio is not None:
        elenco.append((inizio, precedente))
    return elenco


def dentro(serie, inizio, fine):
    return serie[(serie.index >= inizio) & (serie.index <= fine)]


def media(serie, giorno, ora_inizio=11, ora_fine=15):
    maschera = ((serie.index.date == pd.Timestamp(giorno).date())
                & (serie.index.hour >= ora_inizio)
                & (serie.index.hour < ora_fine))
    valori = serie[maschera]
    return valori.mean() if len(valori) else float("nan")


def num(valore):
    if valore != valore:
        return "n.d."
    return "%.0f" % valore


def stampa_tabella(intestazioni, righe):
    colonne = [intestazioni] + [[str(c) for c in riga] for riga in righe]
    larghezze = [max(len(riga[i]) for riga in colonne) + 2
                 for i in range(len(intestazioni))]
    for riga in colonne:
        print("  " + "".join(riga[i].ljust(larghezze[i])
                             for i in range(len(riga))))
    print()


# ---------------------------------------------------------------------------

def principale():
    print("=== GRAFICI 15 |", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "===")
    print()

    file_carico = lotto_piu_recente(sorted(glob.glob(
        os.path.join(CARTELLA_LOG, "10_A65_*.xml"))))
    file_gen = lotto_piu_recente(sorted(glob.glob(
        os.path.join(CARTELLA_LOG, "10_A75_*.xml"))))
    file_flussi = lotto_piu_recente(sorted(glob.glob(
        os.path.join(CARTELLA_LOG, "12_A11_*.xml"))))
    file_prezzi = sorted(glob.glob(os.path.join(CARTELLA_LOG, "04_prezzi_*.csv")))
    file_limiti = sorted(glob.glob(os.path.join(CARTELLA_LOG,
                                                "16_limiti_transito_*.csv")))
    if not (file_carico and file_gen and file_flussi and file_prezzi):
        print("Mancano dei file. Interrompo.")
        return
    print("Carico      : %d file" % len(file_carico))
    print("Generazione : %d file" % len(file_gen))
    print("Flussi      : %d file" % len(file_flussi))
    print("Prezzi      : %s" % os.path.basename(file_prezzi[-1]))
    if file_limiti:
        print("Tetti       : %s" % os.path.basename(file_limiti[-1]))
    else:
        print("Tetti       : nessun file 16_limiti_transito_*.csv"
              " -> lancia prima lo script 16 se vuoi la linea del tetto")
    print()

    # ---- carico -----------------------------------------------------------
    righe = []
    for percorso in file_carico:
        for codice, psr, istante, valore in leggi_gl(percorso):
            righe.append((NOMI_ZONE.get(codice, codice), istante, valore))
    carico = pd.DataFrame(righe, columns=["zona", "istante", "mw"])
    carico = carico.pivot_table(index="istante", columns="zona",
                                values="mw", aggfunc="sum")
    carico.index = carico.index.tz_convert("Europe/Rome")

    # ---- generazione ------------------------------------------------------
    righe = []
    for percorso in file_gen:
        for codice, psr, istante, valore in leggi_gl(percorso):
            righe.append((NOMI_ZONE.get(codice, codice), fetta_fonte(psr),
                          istante, valore))
    gen = pd.DataFrame(righe, columns=["zona", "fonte", "istante", "mw"])
    gen = gen.pivot_table(index=["zona", "istante"], columns="fonte",
                          values="mw", aggfunc="sum")
    gen = gen.reindex(columns=FONTI).fillna(0.0)

    zone_generazione = [z for z in MACRO_SUD
                        if z in list(gen.index.get_level_values(0))]
    zone_carico = [z for z in MACRO_SUD if z in list(carico.columns)]

    macro = gen.loc[zone_generazione].groupby(level="istante").sum()
    macro.index = macro.index.tz_convert("Europe/Rome")
    carico_macro = carico[zone_carico].sum(axis=1)

    comune = macro.index.intersection(carico_macro.index)
    macro = macro.reindex(comune)
    carico_macro = carico_macro.reindex(comune)
    surplus = macro.sum(axis=1) - carico_macro

    # ---- flussi netti -----------------------------------------------------
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
        tutti = a.index.union(b.index)
        netti[etichetta] = a.reindex(tutti).fillna(0.0) - b.reindex(tutti).fillna(0.0)
    corridoio = netti.get("SUD -> CSUD", pd.Series(dtype="float64"))

    prezzi = leggi_prezzi_csv(file_prezzi[-1])
    prezzo_sud = prezzi["IT Sud"] if "IT Sud" in prezzi.columns else prezzi.iloc[:, 0]
    prezzo_csud = (prezzi["IT Centro-Sud"] if "IT Centro-Sud" in prezzi.columns
                   else prezzi.iloc[:, 0])

    # ---- tetto di transito dichiarato da Terna (script 16) ----------------
    tetto = pd.Series(dtype="float64")
    tetto_provvisorio = pd.Series(dtype="float64")
    if file_limiti:
        tetto = leggi_limiti(file_limiti[-1], "limite_definitivo")
        tetto_provvisorio = leggi_limiti(file_limiti[-1], "limite_provvisorio")
        if tetto.empty:
            print("Il file dei tetti non contiene la serie 'limite_definitivo'.\n")

    # ---- numeri -----------------------------------------------------------
    print("############ A) MEDIE 11:00-15:00 (MW; prezzi in EUR/MWh) ############")
    intestazioni = ["giorno", "solare", "eolico", "resto", "carico",
                    "surplus", "SUD->CSUD", "tetto SUD->CSUD", "prezzo Sud"]
    righe = []
    for giorno in ["2026-10-16", "2026-10-17", "2026-10-18"]:
        etichetta = pd.Timestamp(giorno).strftime("%d/%m")
        righe.append([
            etichetta,
            num(media(macro["solare"], giorno)),
            num(media(macro["eolico"], giorno)),
            num(media(macro["resto"], giorno)),
            num(media(carico_macro, giorno)),
            num(media(surplus, giorno)),
            num(media(corridoio, giorno)),
            num(media(tetto, giorno)),
            num(media(prezzo_sud, giorno)),
        ])
    stampa_tabella(intestazioni, righe)

    print("############ B) QUARTI D'ORA CON PREZZO SUD <= 1 EUR/MWh ############")
    for inizio_b, fine_b in tratti_veri(prezzo_sud <= 1.0):
        print("  dal %s al %s" % (inizio_b.strftime("%a %d/%m %H:%M"),
                                  fine_b.strftime("%H:%M")))
    zero = prezzo_sud[prezzo_sud <= 1.0]
    print("  in totale: %d quarti d'ora" % len(zero))
    if len(zero):
        valori = corridoio.reindex(corridoio.index.intersection(zero.index))
        altro = surplus.reindex(surplus.index.intersection(zero.index))
        print("  corridoio SUD->CSUD  : medio %.0f | minimo %.0f | massimo %.0f MW"
              % (valori.mean(), valori.min(), valori.max()))
        print("  surplus macrozona Sud: medio %.0f | massimo %.0f MW"
              % (altro.mean(), altro.max()))
    print()

    print("############ C) TETTO DI TRANSITO TERNA vs FLUSSO FISICO ############")
    if tetto.empty:
        print("  Nessun tetto disponibile: lancia lo script 16 e poi di nuovo questo.")
    else:
        intestazioni = ["giorno", "tetto 11-15", "flusso 11-15", "flusso/tetto"]
        righe = []
        for giorno in ["2026-10-16", "2026-10-17", "2026-10-18"]:
            valore_tetto = media(tetto, giorno)
            valore_flusso = media(corridoio, giorno)
            rapporto = (100.0 * valore_flusso / valore_tetto
                        if valore_tetto and valore_tetto == valore_tetto else float("nan"))
            righe.append([pd.Timestamp(giorno).strftime("%d/%m"),
                          num(valore_tetto), num(valore_flusso),
                          "%.0f%%" % rapporto if rapporto == rapporto else "n.d."])
        stampa_tabella(intestazioni, righe)

        if len(zero):
            tetti_zero = tetto.reindex(tetto.index.intersection(zero.index))
            flussi_zero = corridoio.reindex(corridoio.index.intersection(zero.index))
            if len(tetti_zero):
                print("  Nei %d quarti d'ora col prezzo Sud a zero:"
                      % len(zero))
                print("    tetto medio       : %.0f MW" % tetti_zero.mean())
                print("    flusso fisico medio: %.0f MW (%.0f%% del tetto)"
                      % (flussi_zero.mean(),
                         100.0 * flussi_zero.mean() / tetti_zero.mean()))
                print("    massimo flusso     : %.0f MW (tetto minimo %.0f MW)"
                      % (flussi_zero.max(), tetti_zero.min()))
                print()

        caso = pd.Timestamp("2026-10-16").date()
        print("  Dettaglio 16/10, ora per ora (MW):")
        print("  %-6s %10s %12s %10s" % ("ora", "tetto", "flusso", "flusso/tetto"))
        for ora in range(24):
            tetti_ora = tetto[tetto.index.date == caso]
            tetti_ora = tetti_ora[tetti_ora.index.hour == ora]
            flussi_ora = corridoio[corridoio.index.date == caso]
            flussi_ora = flussi_ora[flussi_ora.index.hour == ora]
            if not len(tetti_ora) or not len(flussi_ora):
                continue
            valore_tetto = tetti_ora.mean()
            valore_flusso = flussi_ora.mean()
            print("  %02d:00  %10.0f %12.0f %9.0f%%"
                  % (ora, valore_tetto, valore_flusso,
                     100.0 * valore_flusso / valore_tetto))
    print()

    # ---- pezzi da disegnare -----------------------------------------------
    inizio = FINESTRA_INIZIO
    fine = FINESTRA_FINE

    macro_x = senza_fuso(dentro(macro, inizio, fine))
    carico_x = senza_fuso(dentro(carico_macro, inizio, fine))
    surplus_x = senza_fuso(dentro(surplus, inizio, fine))
    corridoio_x = senza_fuso(dentro(corridoio, inizio, fine))
    tetto_x = senza_fuso(dentro(tetto, inizio, fine))
    tetto_prov_x = senza_fuso(dentro(tetto_provvisorio, inizio, fine))
    prezzo_sud_x = senza_fuso(dentro(prezzo_sud, inizio, fine))
    prezzo_csud_x = senza_fuso(dentro(prezzo_csud, inizio, fine))

    bandi = []
    for inizio_b, fine_b in tratti_veri(prezzo_sud <= 1.0):
        bandi.append((inizio_b.tz_localize(None),
                      (fine_b + timedelta(minutes=15)).tz_localize(None)))

    # ---- figura -----------------------------------------------------------
    figura, assi = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
    figura.subplots_adjust(left=0.07, right=0.98, top=0.95, bottom=0.07, hspace=0.22)

    for asse in assi:
        for inizio_b, fine_b in bandi:
            asse.axvspan(inizio_b, fine_b, color="0.5", alpha=0.18, linewidth=0)
        asse.grid(True, linewidth=0.5, alpha=0.35)
        asse.set_axisbelow(True)

    asse = assi[0]
    asse.stackplot(macro_x.index,
                   macro_x["solare"].values,
                   macro_x["eolico"].values,
                   macro_x["resto"].values,
                   labels=["solare", "eolico", "resto (idro, gas, altro)"],
                   colors=[COLORI_FONTI["solare"], COLORI_FONTI["eolico"],
                           COLORI_FONTI["resto"]],
                   alpha=0.95)
    asse.plot(carico_x.index, carico_x.values, color="black", linewidth=1.8,
              label="carico della macrozona")
    asse.set_title("1) Macrozona Sud (Sud + Calabria + Sicilia): generazione impilata e carico")
    asse.set_ylabel("MW")
    asse.legend(loc="upper right", fontsize=9, ncol=2, framealpha=0.95)
    asse.margins(x=0)

    asse = assi[1]
    asse.plot(surplus_x.index, surplus_x.values, color="#e07a5f",
              linewidth=1.5, label="surplus della macrozona Sud (generazione - carico)")
    asse.plot(corridoio_x.index, corridoio_x.values, color="#2b6cb0",
              linewidth=1.8, label="flusso fisico Sud -> Centro-Sud (A11)")
    if len(tetto_x):
        comune = tetto_x.index.intersection(tetto_prov_x.index)
        identici = (len(comune) > 0 and
                    (tetto_x.reindex(comune) - tetto_prov_x.reindex(comune))
                    .abs().max() == 0)
        if len(tetto_prov_x) and not identici:
            asse.plot(tetto_prov_x.index, tetto_prov_x.values, color="0.5",
                      linewidth=1.6, linestyle=":", drawstyle="steps-post",
                      label="tetto provvisorio (solo previsione)")
        asse.plot(tetto_x.index, tetto_x.values, color=COLORE_TETTO,
                  linewidth=2.4, linestyle="--", drawstyle="steps-post",
                  label="tetto di transito dichiarato da Terna: Sud -> Centro-Sud")
    asse.axhline(0, color="black", linewidth=0.6)
    asse.set_title("2) Il surplus cresce, il flusso fisico lo segue solo fino al tetto di Terna\n"
                   "quando il flusso tocca il tetto, i prezzi si separano (pannello 3)")
    asse.set_ylabel("MW")
    asse.legend(loc="lower left", fontsize=9, framealpha=0.95)
    asse.margins(x=0)

    asse = assi[2]
    uguali = (len(prezzo_sud_x) == len(prezzo_csud_x)
              and float((prezzo_sud_x - prezzo_csud_x).abs().max()) < 0.01)
    if uguali:
        asse.plot(prezzo_sud_x.index, prezzo_sud_x.values, color="#c0392b",
                  linewidth=1.8, label="prezzo Sud + Centro-Sud")
    else:
        asse.plot(prezzo_sud_x.index, prezzo_sud_x.values, color="#c0392b",
                  linewidth=1.8, label="prezzo Sud")
        asse.plot(prezzo_csud_x.index, prezzo_csud_x.values, color="#2c3e50",
                  linewidth=1.8, label="prezzo Centro-Sud")
    asse.axhline(0, color="black", linewidth=0.6)
    asse.set_title("3) Prezzo: Sud contro Centro-Sud (la banda grigia e' il prezzo Sud a zero)")
    asse.set_ylabel("EUR/MWh")
    asse.set_xlabel("ora italiana")
    asse.legend(loc="upper left", fontsize=9, framealpha=0.95)
    asse.margins(x=0)
    asse.xaxis.set_major_locator(mdates.DayLocator())
    asse.xaxis.set_major_formatter(mdates.DateFormatter("%a %d/%m"))
    asse.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 12, 18]))
    asse.xaxis.set_minor_formatter(mdates.DateFormatter("%H"))

    percorso_png = os.path.join(CARTELLA_LOG, "15_grafici_" + MARCHIO + ".png")
    figura.savefig(percorso_png, dpi=150)
    plt.close(figura)
    print("Immagine salvata:", percorso_png)
    print()
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


if __name__ == "__main__":
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
