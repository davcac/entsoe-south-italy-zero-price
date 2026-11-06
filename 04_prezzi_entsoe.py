# 04_prezzi_entsoe.py
#
# ENTSO-E - prezzi del mercato del giorno prima (day-ahead) delle 7 zone italiane.
#
# Differenze rispetto a EIA (le trovi anche nel resoconto):
#   - la chiave si chiama "token" e ha la forma di un codice UUID (36 caratteri)
#   - il dato non e' JSON ma XML (un file di testo con dei <tag>)
#   - il documento si chiama "A44" e si chiede per ZONA (in Italia ce ne sono 7)
#
# ATTENZIONE, DETTAGLIO IMPORTANTE (curveType A03):
# ENTSO-E NON scrive un valore per ogni quarto d'ora. Quando il prezzo resta
# identico al quarto d'ora precedente, la posizione viene OMESSA: si passa per
# esempio dalla posizione 35 alla 49, e le posizioni 36..48 valgono come la 35.
# Questo script lo gestisce ("riempimento in avanti") e lo dice nel resoconto:
# senza quel passaggio le medie sarebbero sbagliate.
#
# Cosa produce, in  energy-data\log\ :
#   04_esito_<data_ora>.txt   -> il resoconto che leggi a video
#   04_prezzi_<data_ora>.csv  -> i prezzi completi, una riga per zona e quarto d'ora
#   04_<zona>_<data_ora>.xml  -> la risposta grezza ricevuta (una per zona)
#
# SICUREZZA: qualunque testo stampato (a video o su file) passa dalla maschera,
# che sostituisce i valori letti dal volume. Il token non compare da nessuna parte.
#
# Come si usa: montare il volume su A:, aprire questo file in IDLE, premere F5.

import csv
import os
import sys
import traceback
import xml.etree.ElementTree as ET
import zoneinfo
from datetime import datetime, timedelta, timezone

import requests

PERCORSO = r"A:\secrets.env"
INDIRIZZO = "https://web-api.tp.entsoe.eu/api"
MASCHERA = "***SEGRETO-NASCOSTO***"
NOME_SEGRETO = "ENTSOE_TOKEN"

ROMA = zoneinfo.ZoneInfo("Europe/Rome")

# Zone di mercato italiane: nome leggibile -> codice EIC ufficiale.
ZONE = {
    "IT Nord":        "10Y1001A1001A73I",
    "IT Centro-Nord": "10Y1001A1001A70O",
    "IT Centro-Sud":  "10Y1001A1001A71M",
    "IT Sud":         "10Y1001A1001A788",
    "IT Sicilia":     "10Y1001A1001A75E",
    "IT Sardegna":    "10Y1001A1001A74G",
    "IT Calabria":    "10Y1001C--00096J",
}

# Finestra temporale: gli ultimi 3 giorni di consegna COMPLETI, in ora italiana.
# (il giorno di consegna del mercato va da mezzanotte a mezzanotte italiane)
FINE_LOCALE = datetime(datetime.now(ROMA).year, datetime.now(ROMA).month,
                       datetime.now(ROMA).day, tzinfo=ROMA)      # 00:00 di oggi
INIZIO_LOCALE = FINE_LOCALE - timedelta(days=3)
INIZIO_UTC = INIZIO_LOCALE.astimezone(timezone.utc)
FINE_UTC = FINE_LOCALE.astimezone(timezone.utc)

# ENTSO-E vuole orari in UTC nel formato AAAAMMGGhhmm (nessun separatore).
PERIODO_INIZIO = INIZIO_UTC.strftime("%Y%m%d%H%M")
PERIODO_FINE = FINE_UTC.strftime("%Y%m%d%H%M")

CARTELLA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
os.makedirs(CARTELLA_LOG, exist_ok=True)
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_ESITO = os.path.join(CARTELLA_LOG, "04_esito_" + MARCHIO + ".txt")
FILE_CSV = os.path.join(CARTELLA_LOG, "04_prezzi_" + MARCHIO + ".csv")

# --- maschera dei segreti ------------------------------------------------
SEGRETI = {}


def nascondi(testo):
    for valore in SEGRETI.values():
        if isinstance(valore, str) and len(valore) >= 8:
            testo = testo.replace(valore, MASCHERA)
    return testo


class Doppio:
    """Scrive contemporaneamente a video e nel file di resoconto."""

    def __init__(self, percorso, schermo):
        self.file = open(percorso, "w", encoding="utf-8")
        self.schermo = schermo

    def write(self, testo):
        testo = nascondi(testo)
        self.file.write(testo)
        self.schermo.write(testo)

    def flush(self):
        self.file.flush()
        self.schermo.flush()


def leggi_segreti(percorso):
    segreti = {}
    with open(percorso, encoding="utf-8") as file:
        for riga in file:
            riga = riga.strip()
            if riga == "" or riga.startswith("#") or "=" not in riga:
                continue
            nome, valore = riga.split("=", 1)
            segreti[nome.strip()] = valore.strip()
    return segreti


# --- piccoli aiuti per leggere l'XML -------------------------------------
# I tag hanno un prefisso lungo ("namespace"): <ns0:Point>. Queste funzioni lo
# tolgono, cosi' possiamo cercare "Point" scrivendolo semplicemente.

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
    """Trasforma '2026-10-13T22:00Z' in un datetime (con fuso orario UTC)."""
    testo = testo.strip()
    if testo.endswith("Z"):
        testo = testo[:-1] + "+00:00"
    return datetime.fromisoformat(testo)


def minuti_del_passo(risoluzione):
    """'PT15M' -> 15, 'PT60M' -> 60, 'PT1H' -> 60, 'P1D' -> 1440."""
    if risoluzione.startswith("PT"):
        resto = risoluzione[2:]
        if resto.endswith("M"):
            return int(resto[:-1])
        if resto.endswith("H"):
            return int(resto[:-1]) * 60
    if risoluzione.startswith("P") and risoluzione.endswith("D"):
        return int(risoluzione[1:-1]) * 1440
    return None


def leggi_periodi(radice):
    """Estrae da un documento A44 una voce per ogni TimeSeries/Period.

    Restituisce una lista di dizionari con: inizio, fine, passo (minuti),
    valori forniti {posizione: prezzo}, se le posizioni sono "rade" (A03).
    """
    periodi = []
    for serie in discendenti(radice, "TimeSeries"):
        rade = (testo_di(serie, "curveType") or "").strip().upper() == "A03"
        for periodo in figli(serie, "Period"):
            intervallo = figli(periodo, "timeInterval")
            if not intervallo:
                continue
            inizio = momento(testo_di(intervallo[0], "start"))
            fine = momento(testo_di(intervallo[0], "end"))
            risoluzione = testo_di(periodo, "resolution") or "PT60M"
            minuti = minuti_del_passo(risoluzione)
            if minuti is None:
                continue
            forniti = {}
            for punto in figli(periodo, "Point"):
                posizione = testo_di(punto, "position")
                prezzo = testo_di(punto, "price.amount")
                if posizione is None or prezzo is None:
                    continue
                try:
                    forniti[int(posizione)] = float(prezzo)
                except ValueError:
                    continue
            periodi.append({
                "inizio": inizio,
                "fine": fine,
                "minuti": minuti,
                "forniti": forniti,
                "rade": rade,
            })
    return periodi


def costruisci_serie(periodi, da, a):
    """Costruisce la serie completa (un valore per ogni quarto d'ora) tra 'da' e 'a'.

    Restituisce (valori, forniti, ripetuti, non_pubblicati) dove 'valori' e' un
    dizionario {istante: prezzo o None}.
    """
    grezzi = {}          # istante -> prezzo (solo quelli scritti da ENTSO-E)
    si_ripete = any(periodo["rade"] for periodo in periodi)
    for periodo in periodi:
        salto = timedelta(minutes=periodo["minuti"])
        for posizione, prezzo in periodo["forniti"].items():
            grezzi[periodo["inizio"] + (posizione - 1) * salto] = prezzo

    minuti = min(p["minuti"] for p in periodi) if periodi else 60
    passo = timedelta(minutes=minuti)
    griglia = []
    istante = da
    while istante < a:
        griglia.append(istante)
        istante = istante + passo

    istanti_forniti = sorted(i for i in grezzi if da <= i < a)
    indice = 0
    ultimo = None
    valori = {}
    forniti = 0
    ripetuti = 0
    non_pubblicati = 0
    for istante in griglia:
        while indice < len(istanti_forniti) and istanti_forniti[indice] <= istante:
            ultimo = grezzi[istanti_forniti[indice]]
            indice += 1
        if istante in grezzi:
            valori[istante] = grezzi[istante]
            forniti += 1
        elif ultimo is not None and si_ripete:
            valori[istante] = ultimo       # posizione omessa = valore ripetuto
            ripetuti += 1
        else:
            valori[istante] = None
            non_pubblicati += 1
    return valori, forniti, ripetuti, non_pubblicati


def chiedi_prezzi(token, zona):
    parametri = {
        "securityToken": token,
        "documentType": "A44",
        "in_Domain": zona,
        "out_Domain": zona,
        "periodStart": PERIODO_INIZIO,
        "periodEnd": PERIODO_FINE,
    }
    return requests.get(INDIRIZZO, params=parametri, timeout=60)


def motivi(radice):
    elenco = []
    for motivo in discendenti(radice, "Reason"):
        codice = testo_di(motivo, "code") or "?"
        descrizione = testo_di(motivo, "text") or "?"
        elenco.append(codice + " - " + descrizione)
    return elenco


def ora_italiana(istante):
    return istante.astimezone(ROMA).strftime("%d/%m %H:%M")


def principale():
    print("=== AVVIO", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "===")
    print("Resoconto :", FILE_ESITO)
    print("Dati (CSV):", FILE_CSV)
    print()

    segreti = leggi_segreti(PERCORSO)
    SEGRETI.update(segreti)
    print("Segreti letti da", PERCORSO, "->", list(segreti.keys()))
    print()

    token = segreti.get(NOME_SEGRETO, "")
    print("Token ENTSO-E:", len(token), "caratteri")
    if len(token) != 36:
        print("ATTENZIONE: un token ENTSO-E ha 36 caratteri, nella forma")
        print("            xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.")
        print("            Letto:", len(token), "caratteri -> non chiamo l'API.")
        return

    print("Finestra richiesta (ora italiana):")
    print("  da", INIZIO_LOCALE.strftime("%d/%m/%Y %H:%M"),
          "a", FINE_LOCALE.strftime("%d/%m/%Y %H:%M"))
    print("  (= in UTC:", PERIODO_INIZIO, "->", PERIODO_FINE + ")")
    print("  zone:", len(ZONE))
    print()

    righe_csv = []
    riepilogo = []

    for nome_zona, codice in ZONE.items():
        print("---", nome_zona, "(" + codice + ")")
        risposta = chiedi_prezzi(token, codice)
        print("  stato HTTP:", risposta.status_code)

        nome_file = "04_" + nome_zona.replace(" ", "_").replace("(", "").replace(")", "")
        percorso_xml = os.path.join(CARTELLA_LOG, nome_file + "_" + MARCHIO + ".xml")
        with open(percorso_xml, "w", encoding="utf-8") as file:
            file.write(nascondi(risposta.text))
        print("  risposta salvata:", os.path.basename(percorso_xml))
        print("  tipo di risposta:", risposta.headers.get("Content-Type", ""))

        try:
            radice = ET.fromstring(risposta.text)
        except ET.ParseError:
            print("  la risposta NON e' un XML valido. Prime righe:")
            print("   ", risposta.text.strip().replace("\n", " ")[:300])
            riepilogo.append((nome_zona, 0, 0, 0, None, None, None))
            print()
            continue

        print("  tipo documento:", senza_namespace(radice.tag))
        periodi = leggi_periodi(radice)
        if not periodi:
            for motivo in motivi(radice):
                print("  motivo indicato da ENTSO-E:", motivo)
            riepilogo.append((nome_zona, 0, 0, 0, None, None, None))
            print()
            continue

        rade = sum(1 for periodo in periodi if periodo["rade"])
        print("  periodi con posizioni 'rade' (curveType A03):", rade, "su", len(periodi))
        if rade:
            print("    -> le posizioni omesse ripetono il valore precedente")
        print("  passo temporale (minuti):", sorted({p["minuti"] for p in periodi}))

        valori, forniti, ripetuti, non_pubblicati = costruisci_serie(periodi, INIZIO_UTC, FINE_UTC)
        print("  quarti d'ora nella finestra:", len(valori))
        print("    scritti da ENTSO-E      :", forniti)
        print("    ricostruiti (ripetizione):", ripetuti)
        print("    non pubblicati          :", non_pubblicati)

        buoni = {i: v for i, v in valori.items() if v is not None}
        if not buoni:
            riepilogo.append((nome_zona, len(valori), forniti, ripetuti, None, None, None))
            print()
            continue

        media = sum(buoni.values()) / len(buoni)
        istante_min = min(buoni, key=lambda i: buoni[i])
        istante_max = max(buoni, key=lambda i: buoni[i])
        print("  prezzo EUR/MWh: min %s (%s) | max %s (%s) | media %.2f"
              % (buoni[istante_min], ora_italiana(istante_min),
                 buoni[istante_max], ora_italiana(istante_max), media))
        riepilogo.append((nome_zona, len(valori), forniti, ripetuti,
                          media, buoni[istante_min], buoni[istante_max]))

        for istante in sorted(valori):
            righe_csv.append([
                nome_zona, codice,
                istante.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                istante.astimezone(ROMA).strftime("%Y-%m-%d %H:%M"),
                "" if valori[istante] is None else ("%.2f" % valori[istante]),
            ])
        print()

    with open(FILE_CSV, "w", encoding="utf-8", newline="") as file:
        scrittore = csv.writer(file)
        scrittore.writerow(["zona", "codice_eic", "ora_utc", "ora_italiana", "prezzo_eur_mwh"])
        scrittore.writerows(righe_csv)
    print("Righe scritte nel CSV:", len(righe_csv))
    print()

    print("=== RIEPILOGO (EUR/MWh) ===")
    print("  %-16s %6s %7s %7s %9s %8s %8s" %
          ("zona", "quarti", "scritti", "ripet.", "media", "min", "max"))
    for nome_zona, quarti, forniti, ripetuti, media, minimo, massimo in riepilogo:
        if media is None:
            print("  %-16s %6d %7d %7d   (nessun dato)" % (nome_zona, quarti, forniti, ripetuti))
        else:
            print("  %-16s %6d %7d %7d %9.2f %8.2f %8.2f"
                  % (nome_zona, quarti, forniti, ripetuti, media, minimo, massimo))
    print()
    print("Nota: 'scritti' sono i valori presenti nel file ENTSO-E; 'ripet.' quelli")
    print("ricostruiti perche' ENTSO-E omette le posizioni con prezzo ripetuto.")


SCHERMO = sys.stdout
RESOCONTO = Doppio(FILE_ESITO, SCHERMO)
sys.stdout = RESOCONTO

try:
    principale()
except Exception as errore:
    print("ERRORE:", type(errore).__name__, errore)
    print("Dettagli tecnici (i segreti restano mascherati):")
    print(traceback.format_exc())
else:
    print("FINE: esecuzione conclusa senza errori.")
finally:
    RESOCONTO.flush()
    RESOCONTO.file.close()
    sys.stdout = SCHERMO
