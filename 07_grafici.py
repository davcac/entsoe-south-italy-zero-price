# 07_grafici.py
#
# Quattro grafici utili, tutti dagli STESSI dati gia' scaricati (il CSV dello
# script 04). Ogni pannello risponde a una domanda diversa:
#
#   1) curva di durata   -> per quale % del tempo il prezzo sta sopra X?
#   2) mappa ora/giorno  -> il ritmo della giornata e se cambia fra i giorni
#   3) dispersione Nord/Sud -> quanto spesso Nord e Sud hanno lo STESSO prezzo
#   4) media per zona e giorno -> confronto fra i giorni
#
# Come nello script 06, le zone con serie identica sono disegnate come UNA
# sola linea con piu' nomi in legenda (evita le linee nascoste una sotto
# l'altra). Per vedere ogni zona per se', usare lo script 08.
#
# Non serve il volume cifrato e non apre finestre: salva un .png.
# Uscita: energy-data\log\07_grafici_<data_ora>.png

import glob
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CARTELLA = os.path.dirname(os.path.abspath(__file__))
CARTELLA_LOG = os.path.join(CARTELLA, "log")
os.makedirs(CARTELLA_LOG, exist_ok=True)
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_IMMAGINE = os.path.join(CARTELLA_LOG, "07_grafici_" + MARCHIO + ".png")


def raggruppa_zone_identiche(tabella):
    """Zone con la stessa identica serie di prezzi: un gruppo = una linea."""
    gruppi = []
    for nome in tabella.columns:
        for gruppo in gruppi:
            if tabella[nome].equals(tabella[gruppo[0]]):
                gruppo.append(nome)
                break
        else:
            gruppi.append([nome])
    return gruppi


def principale():
    elenco = sorted(glob.glob(os.path.join(CARTELLA_LOG, "04_prezzi_*.csv")))
    if not elenco:
        print("Non trovo nessun file 04_prezzi_*.csv in", CARTELLA_LOG)
        return
    percorso = elenco[-1]
    print("Dati:", os.path.basename(percorso))

    dati = pd.read_csv(percorso)
    dati["quando"] = pd.to_datetime(dati["ora_italiana"], format="%Y-%m-%d %H:%M")
    tabella = dati.pivot(index="quando", columns="zona", values="prezzo_eur_mwh")
    gruppi = raggruppa_zone_identiche(tabella)
    print("Quarti d'ora:", len(tabella), "| zone:", len(tabella.columns))
    for gruppo in gruppi:
        print("   gruppo identico:", " + ".join(gruppo))
    print()

    figura, assi = plt.subplots(2, 2, figsize=(15, 11))

    # --- 1) curva di durata ------------------------------------------------
    # Ordino i prezzi dal piu' alto al piu' basso: sull'asse x la "% del tempo"
    # (0% = il quarto d'ora piu' caro, 100% = il piu' economico).
    assi[0, 0].set_title("1) Curva di durata: per che % del tempo il prezzo sta sopra X\n"
                         "le zone con lo stesso prezzo sono una linea sola, con piu' nomi")
    for gruppo in gruppi:
        valori = tabella[gruppo[0]].sort_values(ascending=False).values
        percentuale = (1 + np.arange(len(valori))) / len(valori) * 100
        assi[0, 0].plot(percentuale, valori, linewidth=1.0 + 0.7 * len(gruppo),
                        label=" + ".join(gruppo))
    assi[0, 0].set_xlabel("% del tempo")
    assi[0, 0].set_ylabel("EUR/MWh")
    assi[0, 0].grid(alpha=0.3)
    assi[0, 0].legend(fontsize=8)

    print("--- 1) quota di tempo con prezzo basso (per zona) ---")
    print("%-16s %9s %9s %9s %7s" % ("zona", "<50", "<100", "<150", "= 0"))
    for nome in tabella.columns:
        serie = tabella[nome]
        print("%-16s %8.1f%% %8.1f%% %8.1f%% %7d" % (
            nome, (serie < 50).mean() * 100, (serie < 100).mean() * 100,
            (serie < 150).mean() * 100, (serie == 0).sum()))
    print()

    # --- 2) mappa ora del giorno / giorno ---------------------------------
    media_zone = tabella.mean(axis=1)
    provvisorio = pd.DataFrame({
        "ora": media_zone.index.hour,
        "indice_ora": np.arange(len(media_zone)) // 4,
        "valore": media_zone.values,
    })
    matrice_ora = provvisorio.pivot_table(index="ora", columns="indice_ora",
                                          values="valore", aggfunc="mean")
    immagine = assi[0, 1].imshow(matrice_ora.values, aspect="auto", origin="lower",
                                 cmap="turbo")
    assi[0, 1].set_title("2) Mappa ora del giorno / periodo (prezzo medio delle zone)\n"
                         "ogni colonna e' un'ora: si vede il ritmo di ogni giornata")
    assi[0, 1].set_ylabel("ora del giorno")
    assi[0, 1].set_xlabel("periodo")
    giorni = sorted({q.strftime("%d/%m") for q in media_zone.index})
    assi[0, 1].set_xticks([24 * i for i in range(len(giorni))], giorni)
    figura.colorbar(immagine, ax=assi[0, 1], label="EUR/MWh")

    # --- 3) dispersione Nord vs Sud --------------------------------------
    nord = tabella["IT Nord"]
    sud = tabella["IT Sud"]
    uguali = int((nord == sud).sum())
    assi[1, 0].scatter(nord, sud, s=6, alpha=0.6, color="tab:blue")
    assi[1, 0].plot([tabella.min().min(), tabella.max().max()],
                    [tabella.min().min(), tabella.max().max()],
                    color="black", linewidth=1, linestyle="--")
    assi[1, 0].set_title("3) Ogni quarto d'ora: prezzo Nord (x) contro prezzo Sud (y)\n"
                         "sulla diagonale = stesso prezzo: %d quarti su %d (%.0f%%)"
                         % (uguali, len(nord), 100 * uguali / len(nord)))
    assi[1, 0].set_xlabel("IT Nord, EUR/MWh")
    assi[1, 0].set_ylabel("IT Sud, EUR/MWh")
    assi[1, 0].grid(alpha=0.3)

    # --- 4) media per zona e giorno ---------------------------------------
    dati["giorno"] = dati["quando"].dt.strftime("%d/%m")
    per_giorno = dati.pivot_table(index="zona", columns="giorno",
                                  values="prezzo_eur_mwh")
    per_giorno.plot(kind="bar", ax=assi[1, 1], width=0.8)
    assi[1, 1].set_title("4) Prezzo medio per zona e per giorno\n"
                         "barre affiancate: qui nessuna zona viene coperta")
    assi[1, 1].set_xlabel("zona")
    assi[1, 1].set_ylabel("EUR/MWh")
    assi[1, 1].grid(alpha=0.3, axis="y")
    assi[1, 1].legend(fontsize=8, title="giorno")

    figura.tight_layout()
    figura.savefig(FILE_IMMAGINE, dpi=110)
    plt.close(figura)
    print("--- media per zona e giorno ---")
    print(per_giorno.round(2).to_string())
    print()
    print("Immagine salvata:", FILE_IMMAGINE)


principale()
