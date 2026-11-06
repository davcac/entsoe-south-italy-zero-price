# 16_limiti_transito.py
#
# SCARICA I "TETTI" DI TRANSITO TRA ZONE DI MERCATO ITALIANE.
#
# Chi decide il tetto e chi lo usa:
#   - TERNA (gestore della rete) DECIDE il limite di transito tra due zone:
#     deve garantire la sicurezza del sistema (criterio n-1, cioe' la rete
#     deve tenere anche se salta un elemento). Il valore del giorno viene
#     calcolato dai centri di coordinamento regionali (Coreso, Esperia)
#     entro le 9:30 del giorno prima (D-1).
#   - GME (gestore del mercato) lo USA: l'asta day-ahead (MGP) prende il
#     tetto come un dato di fatto. Se il trasporto richiesto verso il Sud
#     supera il tetto, il mercato separa i prezzi: e' la conseguenza,
#     non un rimedio.
#
# Da dove: portale dati di Terna -> https://dati.terna.it/download-center
#   sezione "Mercato e adeguatezza" -> "Limiti di transito tra zone di mercato".
#   Le tre voci che ci servono:
#     - "Limiti di transito definitivi"   (endpoint MGPTransitLimit)
#       = tetto orario della giornata di consegna, quello in vigore quando
#         e' girato il mercato day-ahead. QUESTA e' la serie da confrontare
#         con il flusso fisico.
#     - "Limiti di transito provvisori"   (endpoint ForecastTransitLimit)
#       = previsione pubblicata prima, piatta e piu' alta.
#     - "Margini di transito"             (endpoint TransitMargins)
#       = margine residuo (tetto meno programma) dopo ogni sessione MSD.
#
# L'indirizzo qui sotto e' lo stesso che usa il sito quando premi "Download
# Data": e' pubblico, NON serve registrazione e NON serve nessuna chiave
# (quindi niente volume cifrato).
#
# Uscite in log\ (il marchio e' data e ora di esecuzione, cosi' non
# sovrascrive nulla):
#   16_definitivi_<marchio>.xlsx
#   16_provvisori_<marchio>.xlsx
#   16_margini_<marchio>.xlsx
#   16_limiti_transito_<marchio>.csv   <- questo lo legge lo script 15
#
# Formato del CSV (formato "lungo": una riga = un valore):
#   serie,data_ora,zona_da,zona_a,valore_MW
#   limite_definitivo,2026-10-16 12:00,South,Centre-South,2400.00
#
# Come si usa: apri il file in IDLE e premi F5. Non apre finestre.

import csv
import os
import urllib.parse
import urllib.request
from datetime import datetime

import openpyxl

CARTELLA = os.path.dirname(os.path.abspath(__file__))
CARTELLA_LOG = os.path.join(CARTELLA, "log")
os.makedirs(CARTELLA_LOG, exist_ok=True)
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

INDIRIZZO = "https://dati.terna.it/api/sitecore/dati/downloadcenter/records"

# Quale anno e mese scaricare (la pagina di Terna filtra per anno + mese).
ANNO = 2026
MESE = 10

# Quali confini scaricare. Attenzione: i nomi vanno scritti in INGLESE e
# separati (zona_da, zona_a) come fa il sito, anche nella versione italiana.
#   Sud -> Centro-Sud  = il corridoio del caso del 16/10/2026
CONFINI = [
    ("Sud -> Centro-Sud", "South", "Centre-South"),
]

# Le tre serie: chiave del file, nome del dataset di Terna, nome della serie.
SERIE = [
    ("definitivi", "MGPTransitLimit", "limite_definitivo"),
    ("provvisori", "ForecastTransitLimit", "limite_provvisorio"),
    ("margini", "TransitMargins", "margine"),
]

# Un mese di valori orari e' meno di 1000 righe; i margini quarter d'ora
# sono circa 6000. 10000 basta e avanza.
DIMENSIONE_PAGINA = 10000


# ---------------------------------------------------------------------------
# scaricamento
# ---------------------------------------------------------------------------

def scarica(dataset, zona_da, zona_a, anno=ANNO, mese=MESE,
            dimensione=DIMENSIONE_PAGINA):
    """Chiede a Terna i dati e restituisce il contenuto del file xlsx."""
    parametri = {
        "f": "xlsx",
        "filterDataset": dataset,
        "filterZoneFrom": zona_da,
        "filterZoneTo": zona_a,
        "filterYear": str(anno),
        "filterMonth": str(mese),
        "orderByColumn": "Date",
        "orderByDir": "desc",
        "pageSize": str(dimensione),
        "db": "dati",
    }
    indirizzo = INDIRIZZO + "?" + urllib.parse.urlencode(parametri)
    richiesta = urllib.request.Request(indirizzo,
                                       headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(richiesta, timeout=90) as risposta:
        return risposta.read()


def leggi_foglio(percorso):
    """Intestazioni e righe di dati di un file xlsx di Terna.

    L'ultima riga NON e' un dato: e' una riga di servizio che ricorda i
    filtri applicati ("Applied filters: ..."). La si riconosce perche' la
    prima colonna non e' una data.
    """
    foglio = openpyxl.load_workbook(percorso, data_only=True).active
    righe = list(foglio.iter_rows(values_only=True))
    if not righe:
        return [], []
    intestazioni = list(righe[0])
    dati = [riga for riga in righe[1:] if hasattr(riga[0], "hour")]
    return intestazioni, dati


def indice_colonna(intestazioni, inizio):
    for posizione, nome in enumerate(intestazioni):
        if nome and str(nome).strip().lower().startswith(inizio):
            return posizione
    return None


def estrai(percorso, etichetta, zona_da, zona_a):
    """Da file xlsx di Terna a righe (serie, data_ora, zona_da, zona_a, MW)."""
    intestazioni, dati = leggi_foglio(percorso)
    if not dati:
        return []
    pos_data = indice_colonna(intestazioni, "date")
    pos_da = indice_colonna(intestazioni, "zone from")
    pos_a = indice_colonna(intestazioni, "zone to")
    pos_sessione = indice_colonna(intestazioni, "session")
    pos_valore = None
    for inizio in ("forecast", "transit limit", "margin"):
        pos_valore = indice_colonna(intestazioni, inizio)
        if pos_valore is not None:
            break
    if pos_valore is None:
        print("     colonne inattese:", intestazioni)
        return []

    righe = []
    for riga in dati:
        valore = riga[pos_valore]
        if valore is None:
            continue
        nome = etichetta
        if pos_sessione is not None:
            nome = etichetta + "_" + str(riga[pos_sessione])
        righe.append((nome,
                      riga[pos_data],
                      riga[pos_da] if pos_da is not None else zona_da,
                      riga[pos_a] if pos_a is not None else zona_a,
                      float(valore)))
    return righe


def scrivi_csv(percorso, righe):
    with open(percorso, "w", newline="", encoding="utf-8") as uscita:
        scrittore = csv.writer(uscita)
        scrittore.writerow(["serie", "data_ora", "zona_da", "zona_a", "valore_MW"])
        for serie, quando, da, a, valore in sorted(righe, key=lambda r: (r[0], r[1])):
            scrittore.writerow([serie, quando.strftime("%Y-%m-%d %H:%M"),
                                da, a, "%.2f" % valore])


def media_finestra(righe, giorno, ora_da=11, ora_a=15):
    """Media dei valori nella finestra oraria indicata."""
    valori = [v for (_, quando, _, _, v) in righe
              if quando.date() == giorno and ora_da <= quando.hour < ora_a]
    return sum(valori) / len(valori) if valori else None


# ---------------------------------------------------------------------------
# programma
# ---------------------------------------------------------------------------

def scarica_tutto():
    """Scarica tutti i confini e tutte le serie. Torna l'archivio e le righe."""
    archivio = {}
    righe_totali = []
    for titolo, zona_da, zona_a in CONFINI:
        print("===== confine %s (%s -> %s) =====" % (titolo, zona_da, zona_a))
        for chiave, dataset, etichetta in SERIE:
            percorso = os.path.join(CARTELLA_LOG,
                                    "16_%s_%s.xlsx" % (chiave, MARCHIO))
            try:
                contenuto = scarica(dataset, zona_da, zona_a)
            except Exception as errore:
                print("  %-12s NON scaricato (%s)" % (chiave, errore))
                continue
            with open(percorso, "wb") as uscita:
                uscita.write(contenuto)
            righe = estrai(percorso, etichetta, zona_da, zona_a)
            if not righe:
                print("  %-12s nessun valore utile" % chiave)
                continue
            archivio[(titolo, chiave)] = righe
            righe_totali.extend(righe)
            print("  %-12s %5d valori   dal %s al %s"
                  % (chiave, len(righe),
                     min(r[1] for r in righe).strftime("%d/%m %H:%M"),
                     max(r[1] for r in righe).strftime("%d/%m %H:%M")))
        print()
    return archivio, righe_totali


def mostra_numeri(archivio):
    for titolo, _, _ in CONFINI:
        definitivi = archivio.get((titolo, "definitivi"), [])
        provvisori = archivio.get((titolo, "provvisori"), [])
        if not definitivi:
            continue
        print("########## %s: tetto orario (limiti definitivi) ##########" % titolo)
        print("  %-12s %8s %8s %8s" % ("giorno", "min", "max", "media"))
        for giorno in sorted({r[1].date() for r in definitivi}):
            valori = [r[4] for r in definitivi if r[1].date() == giorno]
            print("  %-12s %8.0f %8.0f %8.0f"
                  % (giorno.strftime("%d/%m/%Y"), min(valori), max(valori),
                     sum(valori) / len(valori)))
        print()

        caso = datetime(2026, 10, 16).date()
        print("  Il giorno del caso, 16/10/2026, ora per ora (MW):")
        print("  %-6s %12s %12s" % ("ora", "definitivo", "provvisorio"))
        for riga in sorted([r for r in definitivi if r[1].date() == caso],
                           key=lambda r: r[1]):
            provvisorio = [p[4] for p in provvisori if p[1] == riga[1]]
            print("  %-6s %12.0f %12s"
                  % (riga[1].strftime("%H:%M"), riga[4],
                     "%.0f" % provvisorio[0] if provvisorio else "-"))
        print()

        print("  Media 11:00-15:00, la finestra del buco di prezzo:")
        for giorno in (datetime(2026, 10, 16).date(),
                       datetime(2026, 10, 17).date(),
                       datetime(2026, 10, 18).date()):
            tetto = media_finestra(definitivi, giorno)
            print("    %s -> tetto medio %s MW"
                  % (giorno.strftime("%d/%m/%Y"),
                     "%.0f" % tetto if tetto is not None else "n.d."))
        print()


def principale():
    print("############ SCRIPT 16 - LIMITI DI TRANSITO (Terna) ############")
    print("Periodo: %02d/%d" % (MESE, ANNO))
    print("Fonte: dati.terna.it, Download Center (dati pubblici, nessuna chiave)")
    print()

    archivio, righe_totali = scarica_tutto()
    if not righe_totali:
        print("Non ho scaricato nulla: controlla la connessione e riprova.")
        return

    percorso_csv = os.path.join(CARTELLA_LOG,
                                "16_limiti_transito_%s.csv" % MARCHIO)
    scrivi_csv(percorso_csv, righe_totali)
    print("CSV salvato:", percorso_csv)
    print()

    mostra_numeri(archivio)

    print("Prossimo passo: lancia lo script 15. Legge l'ultimo")
    print("16_limiti_transito_*.csv e disegna il tetto sopra il flusso fisico.")
    print()
    print("=== FINE ===")


principale()
