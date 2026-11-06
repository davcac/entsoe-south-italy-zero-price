# 08_zone_a_facce.py
#
# Risolve il problema: "una zona sparisce perche' la sua linea si sovrappone a
# quella di un'altra e non capisco sotto chi sta".
#
# Come: invece di un grafico unico con 7 linee, si fanno 7 riquadri (uno per
# zona, "facce"). In ogni riquadro:
#   - linea blu spessa   = la zona del titolo (sempre visibile, sempre sopra)
#   - linee grigie       = le altre sei zone, come sfondo di confronto
# Nel titolo sono elencate le zone che hanno lo STESSO identico prezzo: se la
# linea blu segue esattamente una grigia, quella grigia e' la zona in questione.
#
# L'ottavo riquadro e' una tabella: "in che % dei quarti d'ora queste due zone
# hanno lo stesso prezzo". 100% = serie identica.
#
# Non serve il volume cifrato e non apre finestre: salva un .png.
# Uscita: energy-data\log\08_facce_<data_ora>.png

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
FILE_IMMAGINE = os.path.join(CARTELLA_LOG, "08_facce_" + MARCHIO + ".png")


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
    zone = list(tabella.columns)
    print("Quarti d'ora:", len(tabella), "| zone:", len(zone))
    print()

    # --- tabella di "somiglianza": % di quarti d'ora con lo stesso prezzo ----
    somiglianza = pd.DataFrame(index=zone, columns=zone, dtype=float)
    for prima in zone:
        for seconda in zone:
            somiglianza.loc[prima, seconda] = (tabella[prima] == tabella[seconda]).mean() * 100

    print("Quota di quarti d'ora con lo STESSO prezzo fra due zone (in %):")
    print(somiglianza.round(0).astype(int).to_string())
    print()
    print("Gruppi con serie identica al 100%:")
    for nome in zone:
        gemelle = [z for z in zone if z != nome and tabella[z].equals(tabella[nome])]
        if gemelle:
            print("   %-16s = %s" % (nome, ", ".join(gemelle)))
    print()

    # --- disegno: 7 facce (una per zona) + la tabella ----------------------
    figura, assi = plt.subplots(4, 2, figsize=(15, 14))
    assi = assi.ravel()

    for indice, nome_zona in enumerate(zone):
        riquadro = assi[indice]
        for altra in zone:
            if altra != nome_zona:
                riquadro.plot(tabella.index, tabella[altra],
                              color="lightgray", linewidth=0.8)
        riquadro.plot(tabella.index, tabella[nome_zona],
                      color="tab:blue", linewidth=1.6)
        gemelle = [z for z in zone
                   if z != nome_zona and tabella[z].equals(tabella[nome_zona])]
        titolo = nome_zona
        if gemelle:
            titolo += "   [sempre uguale a: " + ", ".join(gemelle) + "]"
        riquadro.set_title(titolo, fontsize=10)
        riquadro.set_ylabel("EUR/MWh", fontsize=8)
        riquadro.grid(alpha=0.3)
        riquadro.tick_params(labelsize=8)

    # le etichette delle date servono solo sui riquadri in basso
    for indice in range(6):
        assi[indice].tick_params(labelbottom=False)

    # tabella di somiglianza nell'ottavo riquadro
    riquadro = assi[7]
    riquadro.imshow(somiglianza.values, cmap="Blues", vmin=0, vmax=100)
    riquadro.set_xticks(range(len(zone)), zone, rotation=90, fontsize=7)
    riquadro.set_yticks(range(len(zone)), zone, fontsize=7)
    for riga in range(len(zone)):
        for colonna in range(len(zone)):
            valore = somiglianza.values[riga, colonna]
            riquadro.text(colonna, riga, "%.0f" % valore, ha="center", va="center",
                          fontsize=7, color="white" if valore > 60 else "black")
    riquadro.set_title("8) % del tempo con lo STESSO prezzo\n(riga contro colonna)", fontsize=10)

    figura.tight_layout(rect=[0, 0.035, 1, 1])
    figura.text(0.5, 0.012,
                "Linea blu = la zona scritta nel titolo.  Linee grigie = le altre zone.\n"
                "Se la blu segue esattamente una grigia, quella grigia e' la zona con lo stesso prezzo.",
                ha="center", fontsize=9)
    figura.savefig(FILE_IMMAGINE, dpi=110)
    plt.close(figura)
    print("Immagine salvata:", FILE_IMMAGINE)


principale()
