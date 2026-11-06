# 06_grafico_prezzi.py
#
# Disegna i prezzi day-ahead delle 7 zone italiane con TRE pannelli:
#   1. sopra    -> tutte le zone insieme (livello assoluto)
#   2. in mezzo -> DIFFERENZA di ogni zona dal Nord
#   3. sotto    -> profilo medio della giornata
#
# REGOLA IMPORTANTE SULLA VISUALIZZAZIONE (leggere prima di guardare i grafici):
# matplotlib disegna una linea dopo l'altra. Se due zone hanno lo STESSO
# identico prezzo, la seconda linea copre la prima: la prima zona sparisce.
# Qui NON disegniamo piu' linee sovrapposte: quando due o piu' zone hanno la
# stessa serie, viene disegnata UNA sola linea e nella legenda compare
# "IT Sud + IT Calabria". Cosi' si sa sempre chi c'e' sotto.
# Le linee che rappresentano piu' di una zona sono anche piu' spesse.
#
# Se invece serve vedere ogni zona per se', c'e' lo script 08 (facce).
#
# Non serve il volume cifrato e non apre finestre: salva un .png.
# Uscita: energy-data\log\06_grafico_<data_ora>.png

import glob
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

CARTELLA = os.path.dirname(os.path.abspath(__file__))
CARTELLA_LOG = os.path.join(CARTELLA, "log")
os.makedirs(CARTELLA_LOG, exist_ok=True)
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_IMMAGINE = os.path.join(CARTELLA_LOG, "06_grafico_" + MARCHIO + ".png")

ZONA_RIFERIMENTO = "IT Nord"


def raggruppa_zone_identiche(tabella):
    """Raggruppa le zone che hanno la stessa identica serie di prezzi.

    Restituisce una lista di gruppi: [['IT Nord', 'IT Centro-Nord'],
    ['IT Sud', 'IT Calabria'], ...]. Chiamiamo "identiche" due zone che hanno
    lo stesso prezzo (ai due decimali pubblicati da ENTSO-E) in tutti i quarti
    d'ora. Un gruppo = una sola linea da disegnare.
    """
    gruppi = []
    for nome in tabella.columns:
        for gruppo in gruppi:
            if tabella[nome].equals(tabella[gruppo[0]]):
                gruppo.append(nome)
                break
        else:
            gruppi.append([nome])
    return gruppi


def etichetta_di(gruppo):
    return " + ".join(gruppo)


def principale():
    # 1) quale file di dati leggiamo (il piu' recente)
    elenco = sorted(glob.glob(os.path.join(CARTELLA_LOG, "04_prezzi_*.csv")))
    if not elenco:
        print("Non trovo nessun file 04_prezzi_*.csv in", CARTELLA_LOG)
        print("Prima lancia lo script 04 (con il volume montato).")
        return
    percorso = elenco[-1]
    print("Dati:", os.path.basename(percorso))

    dati = pd.read_csv(percorso)
    dati["quando"] = pd.to_datetime(dati["ora_italiana"], format="%Y-%m-%d %H:%M")
    tabella = dati.pivot(index="quando", columns="zona", values="prezzo_eur_mwh")
    gruppi = raggruppa_zone_identiche(tabella)

    print("Quarti d'ora:", len(tabella), "| zone:", len(tabella.columns))
    print("Gruppi di zone con serie identica (in legenda compare come 'A + B'):")
    for gruppo in gruppi:
        print("   " + etichetta_di(gruppo))
    print()

    tutte_uguali = (tabella.nunique(axis=1) == 1).sum()
    quota = 100.0 * tutte_uguali / len(tabella)
    print("Quarti d'ora con lo stesso prezzo in tutte le zone: %d su %d (%.0f%%)"
          % (tutte_uguali, len(tabella), quota))
    print()

    figura, (sopra, mezzo, sotto) = plt.subplots(3, 1, figsize=(11.5, 13))

    # --- pannello 1: tutte le zone, livello assoluto ----------------------
    for gruppo in gruppi:
        serie = tabella[gruppo[0]]
        spesso = 1.0 + 0.7 * len(gruppo)          # piu' zone = linea piu' spessa
        sopra.plot(tabella.index, serie, linewidth=spesso, alpha=0.8,
                   label=etichetta_di(gruppo))
    sopra.set_title(
        "1) Tutte le zone, ogni quarto d'ora, nel livello assoluto\n"
        "Le zone con lo stesso prezzo sono UNA linea con piu' nomi in legenda; "
        "%.0f%% dei quarti d'ora ha un prezzo unico per tutte le zone" % quota,
        fontsize=10)
    sopra.set_ylabel("EUR/MWh")
    sopra.grid(alpha=0.3)
    sopra.legend(ncol=3, fontsize=8)

    # --- pannello 2: differenza da Nord ----------------------------------
    print("Differenza di ogni zona dal Nord (%s):" % ZONA_RIFERIMENTO)
    for gruppo in gruppi:
        if ZONA_RIFERIMENTO in gruppo:
            continue
        differenza = tabella[gruppo[0]] - tabella[ZONA_RIFERIMENTO]
        mezzo.plot(tabella.index, differenza, linewidth=1.0 + 0.7 * len(gruppo),
                   label=etichetta_di(gruppo))
        print("  %-28s media %7.2f | minima %8.2f | massima %8.2f | quarti diversi da 0: %d"
              % (etichetta_di(gruppo), differenza.mean(), differenza.min(),
                 differenza.max(), (differenza != 0).sum()))
    mezzo.axhline(0, color="black", linewidth=1.0)
    mezzo.set_title("2) Ogni zona MENO il Nord (%s): sotto zero = zona piu' economica\n"
                    "questa e' la lettura 'da desk': quanto la rete tiene separati i prezzi"
                    % ZONA_RIFERIMENTO)
    mezzo.set_ylabel("EUR/MWh (differenza)")
    mezzo.grid(alpha=0.3)
    mezzo.legend(ncol=3, fontsize=9)
    print()

    # --- pannello 3: profilo medio della giornata -------------------------
    dati["ora_del_giorno"] = dati["quando"].dt.hour
    per_ora = dati.groupby("ora_del_giorno")["prezzo_eur_mwh"].mean()
    sotto.bar(per_ora.index, per_ora.values, color="steelblue")
    sotto.set_title("3) Profilo medio della giornata (media di tutte le zone)")
    sotto.set_xlabel("ora italiana")
    sotto.set_ylabel("EUR/MWh")
    sotto.grid(alpha=0.3, axis="y")
    print("Profilo orario medio: min %.2f alle %02d:00 | max %.2f alle %02d:00"
          % (per_ora.min(), per_ora.idxmin(), per_ora.max(), per_ora.idxmax()))

    figura.tight_layout()
    figura.savefig(FILE_IMMAGINE, dpi=110)
    plt.close(figura)
    print()
    print("Immagine salvata:", FILE_IMMAGINE)


principale()
