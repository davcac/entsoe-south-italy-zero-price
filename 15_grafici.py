# 15_grafici.py
#
# Solo grafici. Nessuna chiave da montare: legge il dataset gia' costruito in
# data/ (carico e generazione, flussi netti, flussi lordi per direzione, prezzi,
# limiti di transito dichiarati da Terna).
#
# Il pannello 2 disegna il LIMITE di transito dichiarato da Terna per il
# corridoio Sud -> Centro-Sud come linea a scalini sopra il flusso fisico.
# E' il confronto che spiega il buco di prezzo: quando il flusso tocca il
# limite, il mercato separa i prezzi.
#
# Tre pannelli con lo stesso asse dei tempi (16-18/10):
#   1) macrozona Sud (Sud + Calabria + Sicilia): generazione impilata e carico
#   2) surplus della macrozona contro le sue tre vie d'uscita, e le entrate
#   3) prezzo Sud contro prezzo Centro-Sud
# La banda grigia segna i quarti d'ora in cui il prezzo del Sud e' a zero.
#
# Uscita: log\15_grafici_<data_ora>.png  e  log\15_esito_<data_ora>.txt
# Si lancia in IDLE con F5.

import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

CARTELLA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
CARTELLA_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_ESITO = os.path.join(CARTELLA_LOG, "15_esito_" + MARCHIO + ".txt")

MACRO_SUD = ["IT Sud", "IT Calabria", "IT Sicilia"]

#: i cinque confini: etichetta del grafico, direzione canonica nel dataset,
#: direzione opposta (serve per i flussi lordi, in export e in import)
BORDI = [
    ("SUD -> CSUD", "IT Sud -> IT Centro-Sud", "IT Centro-Sud -> IT Sud"),
    ("SUD -> GRECIA", "IT Sud -> Greece", "Greece -> IT Sud"),
    ("SICI -> MALTA", "IT Sicilia -> Malta", "Malta -> IT Sicilia"),
    ("CALA -> SUD", "IT Calabria -> IT Sud", "IT Sud -> IT Calabria"),
    ("SICI -> CALA", "IT Sicilia -> IT Calabria", "IT Calabria -> IT Sicilia"),
]

FINESTRA_INIZIO = pd.Timestamp("2026-10-16 00:00", tz="Europe/Rome")
FINESTRA_FINE = pd.Timestamp("2026-10-19 00:00", tz="Europe/Rome")

FONTI = ["solare", "eolico", "resto"]
COLORI_FONTI = {"solare": "#f2c14e", "eolico": "#4c9f70", "resto": "#8d9db6"}


# ---------------------------------------------------------------------------
# lettura del dataset in data/ (niente XML, niente chiavi)
# ---------------------------------------------------------------------------

#: dal dataset (nomi inglesi) alle tre fette del grafico (nomi italiani)
FONTE_DAL_DATASET = {"solar": "solare", "wind": "eolico"}


def indice_locale(tabella):
    """Colonna timestamp_utc -> istanti in ora italiana (tz-aware)."""
    return pd.to_datetime(tabella["timestamp_utc"], utc=True).dt.tz_convert("Europe/Rome")


def leggi_flussi(percorso):
    """cross_border_flows.csv -> {confine canonico: Series di MW netti}."""
    tabella = pd.read_csv(percorso)
    tabella["istante"] = indice_locale(tabella)
    return {confine: gruppo.set_index("istante")["flow_mw"].sort_index()
            for confine, gruppo in tabella.groupby("border")}


def leggi_flussi_direzionali(percorso):
    """cross_border_flows_directional.csv -> {direzione reale: Series di MW lordi}."""
    tabella = pd.read_csv(percorso)
    tabella["istante"] = indice_locale(tabella)
    return {confine: gruppo.set_index("istante")["flow_mw"].sort_index()
            for confine, gruppo in tabella.groupby("border")}


def leggi_carico_generazione(percorso):
    """load_generation.csv -> (carico per zona, generazione per zona e fonte)."""
    tabella = pd.read_csv(percorso)
    tabella["istante"] = indice_locale(tabella)
    carico = (tabella[tabella["source"] == "load"]
              .pivot_table(index="istante", columns="zone", values="mw",
                            aggfunc="sum"))
    generazione = tabella[tabella["source"] != "load"].copy()
    generazione["fonte"] = generazione["source"].map(
        lambda s: FONTE_DAL_DATASET.get(s, "resto"))
    generazione = generazione.pivot_table(index=["zone", "istante"],
                                           columns="fonte", values="mw",
                                           aggfunc="sum")
    return carico, generazione


def leggi_prezzi(percorso):
    """day_ahead_prices.csv -> tabella dei prezzi per zona."""
    tabella = pd.read_csv(percorso)
    tabella["istante"] = indice_locale(tabella)
    return tabella.pivot_table(index="istante", columns="zone",
                               values="price_eur_mwh", aggfunc="last")


def leggi_limiti(percorso, nome_serie, da=None, a=None):
    """transit_limits.csv -> Series di MW della serie richiesta, in ora italiana.

    Con ``da``/``a`` si tiene solo una coppia di zone (il corridoio su cui
    e' dichiarato il limite).
    """
    tabella = pd.read_csv(percorso)
    tabella = tabella[tabella["series"] == nome_serie]
    if da is not None:
        tabella = tabella[(tabella["zone_from"] == da) & (tabella["zone_to"] == a)]
    if tabella.empty:
        return pd.Series(dtype="float64")
    quando = pd.to_datetime(tabella["timestamp_local"], format="%Y-%m-%d %H:%M")
    serie = pd.Series(tabella["value_mw"].values, index=quando)
    serie = serie.sort_index()
    # l'ora dell'ultima domenica di ottobre e' ambigua (si ripete): si sceglie
    # l'ora legale. Il finale di ottobre e' lontano dalla finestra analizzata.
    serie.index = serie.index.tz_localize("Europe/Rome", ambiguous=True,
                                          nonexistent="shift_forward")
    serie = serie[~serie.index.duplicated(keep="last")].sort_index()
    return serie


# ---------------------------------------------------------------------------
# utilita'
# ---------------------------------------------------------------------------

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

    file_carico_gen = os.path.join(CARTELLA_DATA, "load_generation.csv")
    file_flussi = os.path.join(CARTELLA_DATA, "cross_border_flows.csv")
    file_direzionali = os.path.join(CARTELLA_DATA,
                                   "cross_border_flows_directional.csv")
    file_prezzi = os.path.join(CARTELLA_DATA, "day_ahead_prices.csv")
    file_limiti = os.path.join(CARTELLA_DATA, "transit_limits.csv")
    if not all(os.path.exists(p) for p in (file_carico_gen, file_flussi,
                                            file_direzionali, file_prezzi)):
        print("Mancano dei file in data/. Interrompo.")
        return
    print("Dataset     : %s" % CARTELLA_DATA)
    print("Flussi      : %s" % os.path.basename(file_flussi))
    print("Direzionali : %s" % os.path.basename(file_direzionali))
    print("Prezzi      : %s" % os.path.basename(file_prezzi))
    print("Limiti      : %s" % os.path.basename(file_limiti))
    print()

    # ---- carico e generazione ---------------------------------------------
    carico, gen = leggi_carico_generazione(file_carico_gen)
    zone_generazione = [z for z in MACRO_SUD
                        if z in list(gen.index.get_level_values(0))]
    zone_carico = [z for z in MACRO_SUD if z in list(carico.columns)]

    macro = gen.loc[zone_generazione].groupby(level="istante").sum()
    macro = macro.reindex(columns=FONTI).fillna(0.0)
    carico_macro = carico[zone_carico].sum(axis=1)

    comune = macro.index.intersection(carico_macro.index)
    macro = macro.reindex(comune)
    carico_macro = carico_macro.reindex(comune)
    surplus = macro.sum(axis=1) - carico_macro

    # ---- flussi netti e flussi per direzione ------------------------------
    netti_dataset = leggi_flussi(file_flussi)
    direzionali = leggi_flussi_direzionali(file_direzionali)
    netti = {}
    for etichetta, canonico, opposto in BORDI:
        serie = netti_dataset.get(canonico)
        netti[etichetta] = (serie if serie is not None
                            else pd.Series(dtype="float64"))
    corridoio = netti.get("SUD -> CSUD", pd.Series(dtype="float64"))

    # ---- flussi lordi per direzione ---------------------------------------
    # Gli stessi tre confini esterni della macrozona, presi uno per direzione:
    # le uscite (Centro-Sud, Grecia, Malta) e le entrate (i versi opposti).
    indice_comune = surplus.index

    def lordo(chiave):
        serie = direzionali.get(chiave)
        if serie is None or serie.empty:
            return pd.Series(0.0, index=indice_comune)
        return serie.reindex(indice_comune).ffill().fillna(0.0)

    uscite_totali = (lordo("IT Sud -> IT Centro-Sud")
                     + lordo("IT Sud -> Greece")
                     + lordo("IT Sicilia -> Malta"))
    entrate_totali = (lordo("IT Centro-Sud -> IT Sud")
                      + lordo("Greece -> IT Sud")
                      + lordo("Malta -> IT Sicilia"))
    # solo lo scambio NETTO e' confrontabile con il saldo interno della macrozona:
    # gli stessi confini trasportano contemporaneamente potenza in entrata e in
    # uscita, e il flusso lordo puo' quindi superare il surplus.
    netto_totali = uscite_totali - entrate_totali

    # ---- utilizzo di ogni via d'uscita (flusso sul limite di Terna) -------
    # Le tre interfacce esterne della macrozona, con il limite che Terna
    # dichiara per ciascuna. "Greece 2" e' l'interconnessione fisica (500 MW);
    # "Greece" e' il punto di coupling commerciale, che non vincola mai.
    INTERFACCIE = [
        ("IT Sud -> IT Centro-Sud", "South", "Centre-South", "#2b6cb0"),
        ("IT Sud -> Greece", "South", "Greece 2", "#4c9f70"),
        ("IT Sicilia -> Malta", "Sicily", "Malta", "#8d9db6"),
    ]

    def utilizzo(chiave, da, a):
        flusso = lordo(chiave)
        limite = leggi_limiti(file_limiti, "final_transit_limit", da, a)
        if limite.empty:
            return pd.Series(dtype="float64")
        limite = limite.reindex(indice_comune).ffill()
        rapporto = 100.0 * flusso / limite.where(limite > 0)
        return rapporto.dropna()

    prezzi = leggi_prezzi(file_prezzi)
    prezzo_sud = prezzi["IT Sud"] if "IT Sud" in prezzi.columns else prezzi.iloc[:, 0]
    prezzo_csud = (prezzi["IT Centro-Sud"] if "IT Centro-Sud" in prezzi.columns
                   else prezzi.iloc[:, 0])

    # ---- limite di transito dichiarato da Terna ---------------------------
    limite = leggi_limiti(file_limiti, "final_transit_limit")
    if limite.empty:
        print("Il dataset non contiene la serie 'final_transit_limit'.\n")

    # ---- numeri -----------------------------------------------------------
    print("############ A) MEDIE 11:00-15:00 (MW; prezzi in EUR/MWh) ############")
    intestazioni = ["giorno", "solare", "eolico", "resto", "carico",
                    "surplus", "SUD->CSUD", "limite SUD->CSUD", "prezzo Sud"]
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
            num(media(limite, giorno)),
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

    print("############ C) LIMITE DI TRANSITO TERNA vs FLUSSO FISICO ############")
    if limite.empty:
        print("  Nessun limite disponibile: lancia lo script 16 e poi di nuovo questo.")
    else:
        intestazioni = ["giorno", "limite 11-15", "flusso 11-15", "flusso/limite"]
        righe = []
        for giorno in ["2026-10-16", "2026-10-17", "2026-10-18"]:
            valore_limite = media(limite, giorno)
            valore_flusso = media(corridoio, giorno)
            rapporto = (100.0 * valore_flusso / valore_limite
                        if valore_limite and valore_limite == valore_limite else float("nan"))
            righe.append([pd.Timestamp(giorno).strftime("%d/%m"),
                          num(valore_limite), num(valore_flusso),
                          "%.0f%%" % rapporto if rapporto == rapporto else "n.d."])
        stampa_tabella(intestazioni, righe)

        if len(zero):
            tetti_zero = limite.reindex(limite.index.intersection(zero.index))
            flussi_zero = corridoio.reindex(corridoio.index.intersection(zero.index))
            if len(tetti_zero):
                print("  Nei %d quarti d'ora col prezzo Sud a zero:"
                      % len(zero))
                print("    limite medio       : %.0f MW" % tetti_zero.mean())
                print("    flusso fisico medio: %.0f MW (%.0f%% del limite)"
                      % (flussi_zero.mean(),
                         100.0 * flussi_zero.mean() / tetti_zero.mean()))
                print("    massimo flusso     : %.0f MW (limite minimo %.0f MW)"
                      % (flussi_zero.max(), tetti_zero.min()))
                print()

        caso = pd.Timestamp("2026-10-16").date()
        print("  Dettaglio 16/10, ora per ora (MW):")
        print("  %-6s %10s %12s %10s" % ("ora", "limite", "flusso", "flusso/limite"))
        for ora in range(24):
            tetti_ora = limite[limite.index.date == caso]
            tetti_ora = tetti_ora[tetti_ora.index.hour == ora]
            flussi_ora = corridoio[corridoio.index.date == caso]
            flussi_ora = flussi_ora[flussi_ora.index.hour == ora]
            if not len(tetti_ora) or not len(flussi_ora):
                continue
            valore_limite = tetti_ora.mean()
            valore_flusso = flussi_ora.mean()
            print("  %02d:00  %10.0f %12.0f %9.0f%%"
                  % (ora, valore_limite, valore_flusso,
                     100.0 * valore_flusso / valore_limite))
    print()

    print("############ D) BILANCIO DELLA MACROZONA (MW) ############")
    intestazioni = ["giorno", "surplus", "uscite", "entrate", "netto",
                    "non uscito"]
    righe = []
    for giorno in ["2026-10-16", "2026-10-17", "2026-10-18"]:
        s = media(surplus, giorno)
        u = media(uscite_totali, giorno)
        e = media(entrate_totali, giorno)
        righe.append([pd.Timestamp(giorno).strftime("%d/%m"),
                      num(s), num(u), num(e), num(u - e), num(s - (u - e))])
    stampa_tabella(intestazioni, righe)
    print("  'surplus'    = generazione - carico della macrozona Sud")
    print("  'uscite'     = flussi lordi in uscita dai tre confini esterni")
    print("                 (Centro-Sud, Grecia, Malta)")
    print("  'entrate'    = flussi lordi in entrata dagli stessi tre confini")
    print("  'netto'      = uscite - entrate")
    print("  'non uscito' = surplus - netto")
    print("  il saldo interno e lo scambio netto coincidono salvo le perdite")
    print("  di rete, il pompaggio e le differenze di misura.")
    print()

    print("############ E) UTILIZZO DI OGNI VIA D'USCITA (16/10, 11:00-15:00) ############")
    intestazioni = ["via", "limite Terna", "flusso medio", "utilizzo medio",
                    "utilizzo max"]
    righe = []
    giorno = pd.Timestamp("2026-10-16").date()
    for chiave, da, a, _ in INTERFACCIE:
        limite = leggi_limiti(file_limiti, "final_transit_limit", da, a)
        rapporto = utilizzo(chiave, da, a)
        if limite.empty or not len(rapporto):
            continue
        lim = limite[limite.index.date == giorno]
        lim = lim[(lim.index.hour >= 11) & (lim.index.hour < 15)]
        fin = rapporto[(rapporto.index.date == giorno)
                       & (rapporto.index.hour >= 11) & (rapporto.index.hour < 15)]
        righe.append([chiave,
                      "%.0f" % lim.min() if len(lim) else "n.d.",
                      num(media(lordo(chiave), "2026-10-16")),
                      "%.0f%%" % fin.mean() if len(fin) else "n.d.",
                      "%.0f%%" % fin.max() if len(fin) else "n.d."])
    stampa_tabella(intestazioni, righe)
    print("  il limite e' quello dichiarato da Terna per ciascuna interfaccia;")
    print("  100% = interfaccia satura.")
    print()

    # ---- pezzi da disegnare -----------------------------------------------
    inizio = FINESTRA_INIZIO
    fine = FINESTRA_FINE

    macro_x = senza_fuso(dentro(macro, inizio, fine))
    carico_x = senza_fuso(dentro(carico_macro, inizio, fine))
    surplus_x = senza_fuso(dentro(surplus, inizio, fine))
    prezzo_sud_x = senza_fuso(dentro(prezzo_sud, inizio, fine))
    prezzo_csud_x = senza_fuso(dentro(prezzo_csud, inizio, fine))

    bandi = []
    for inizio_b, fine_b in tratti_veri(prezzo_sud <= 1.0):
        bandi.append((inizio_b.tz_localize(None),
                      (fine_b + timedelta(minutes=15)).tz_localize(None)))

    # ---- figura -----------------------------------------------------------
    figura, assi = plt.subplots(4, 1, figsize=(14, 15), sharex=True)
    figura.subplots_adjust(left=0.07, right=0.98, top=0.96, bottom=0.05, hspace=0.28)

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
    netto_x = senza_fuso(dentro(netto_totali, inizio, fine))
    # l'area fra le due curve e' la potenza che non ha potuto uscire
    asse.fill_between(surplus_x.index, netto_x.values, surplus_x.values,
                      where=(surplus_x.values >= netto_x.values),
                      color="#e07a5f", alpha=0.18, linewidth=0,
                      label="potenza che non ha potuto uscire")
    asse.plot(netto_x.index, netto_x.values, color="#2b6cb0", linewidth=1.8,
              label="export netto della macrozona (uscite - entrate)")
    asse.plot(surplus_x.index, surplus_x.values, color="#e07a5f",
              linewidth=1.8, zorder=6,
              label="surplus della macrozona Sud (immissioni - prelievi)")
    asse.axhline(0, color="black", linewidth=0.6)
    asse.set_title("2) Il surplus della macrozona contro il suo export netto: il 16 ottobre il divario si apre")
    asse.set_ylabel("MW")
    asse.legend(loc="upper right", fontsize=9, framealpha=0.95)
    asse.margins(x=0)

    asse = assi[2]
    for chiave, da, a, colore in INTERFACCIE:
        rapporto = utilizzo(chiave, da, a)
        if not len(rapporto):
            continue
        troncata = senza_fuso(dentro(rapporto, inizio, fine))
        asse.plot(troncata.index, troncata.values, color=colore, linewidth=1.6,
                  label=chiave)
    asse.axhline(100, color="#c0392b", linewidth=1.4, linestyle="--")
    asse.set_title("3) Utilizzo di ogni via d'uscita: flusso sul limite dichiarato da Terna\n"
                   "(100% = interfaccia satura)")
    asse.set_ylabel("% del limite")
    asse.set_ylim(-5, 150)
    asse.legend(loc="upper right", fontsize=8, framealpha=0.95)
    asse.margins(x=0)

    asse = assi[3]
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
    asse.set_title("4) Prezzo: Sud contro Centro-Sud (la banda grigia e' il prezzo Sud a zero)")
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
