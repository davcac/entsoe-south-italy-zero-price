# 09_prova_entsoe.py
#
# SCOPO: capire cosa l'API di ENTSO-E restituisce DAVVERO per i documenti che
# ci servono per spiegare il crollo del prezzo nel Sud (16/10, mezzogiorno).
#
# Perche' una "prova" e non uno scarico completo: di questi documenti non
# conosciamo la forma esatta (quale parametro vuole l'API, quali campi tornano
# indietro). Questo script fa 19 richieste piccole (2 giorni di dati su poche
# zone), stampa per ognuna: codice HTTP, se l'XML e' valido, quanti punti sono
# arrivati, e - se ENTSO-E rifiuta - il motivo scritto da ENTSO-E stesso.
#
# Documenti provati:
#   A65  carico totale effettivo (domanda) per zona
#   A75  generazione effettiva per tipo di impianto, per zona
#   A11  flussi fisici fra due zone (Sud -> Centro-Sud, Sicilia -> Calabria)
#   A77/A78/A79/A80  indisponibilita' (impianti e rete): quali esistono
#
# Le risposte che contengono dati vengono salvate in log\09_prova_*.xml: cosi'
# gli script successivi leggono quei file e NON serve piu' montare il volume.
#
# Come si usa: montare il volume su A:, aprire questo file in IDLE, premere F5.

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

ZONE = {
    "IT Nord":        "10Y1001A1001A73I",
    "IT Centro-Nord": "10Y1001A1001A70O",
    "IT Centro-Sud":  "10Y1001A1001A71M",
    "IT Sud":         "10Y1001A1001A788",
    "IT Sicilia":     "10Y1001A1001A75E",
    "IT Sardegna":    "10Y1001A1001A74G",
    "IT Calabria":    "10Y1001C--00096J",
}

# Due giornate intere: venerdi' 16 (giorno del crollo) e sabato 17 (giorno normale)
INIZIO_LOCALE = datetime(2026, 10, 16, 0, 0, tzinfo=ROMA)
FINE_LOCALE = datetime(2026, 10, 18, 0, 0, tzinfo=ROMA)
INIZIO_UTC = INIZIO_LOCALE.astimezone(timezone.utc)
FINE_UTC = FINE_LOCALE.astimezone(timezone.utc)
PERIODO_INIZIO = INIZIO_UTC.strftime("%Y%m%d%H%M")
PERIODO_FINE = FINE_UTC.strftime("%Y%m%d%H%M")

NOMI_PSR = {
    "B01": "biomassa", "B02": "carbone bruno", "B03": "carbone", "B04": "gas",
    "B05": "olio", "B06": "olio", "B07": "olio", "B08": "torba", "B09": "geotermico",
    "B10": "idro pompaggio", "B11": "idro fluente", "B12": "idro serbatoio",
    "B13": "rifiuti", "B14": "nucleare", "B15": "altro", "B16": "solare",
    "B17": "altro", "B18": "eolico offshore", "B19": "eolico onshore", "B20": "altro",
}

CARTELLA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
os.makedirs(CARTELLA_LOG, exist_ok=True)
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_ESITO = os.path.join(CARTELLA_LOG, "09_esito_" + MARCHIO + ".txt")

SEGRETI = {}


def nascondi(testo):
    for valore in SEGRETI.values():
        if isinstance(valore, str) and len(valore) >= 8:
            testo = testo.replace(valore, MASCHERA)
    return testo


class Doppio:
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


def senza_namespace(tag):
    return tag.split("}")[-1]


def figli(elemento, nome):
    return [f for f in list(elemento) if senza_namespace(f.tag) == nome]


def discendenti(radice, nome):
    return [e for e in radice.iter() if senza_namespace(e.tag) == nome]


def testo_di(elemento, nome):
    trovati = figli(elemento, nome)
    return trovati[0].text if trovati else None


def motivi(radice):
    elenco = []
    for motivo in discendenti(radice, "Reason"):
        codice = testo_di(motivo, "code") or "?"
        descrizione = (testo_di(motivo, "text") or "?").strip()
        elenco.append(codice + " - " + descrizione)
    return elenco


def prova(token, etichetta, parametri):
    """Esegue una richiesta e restituisce un riassunto leggibile."""
    parametri = dict(parametri)
    parametri["securityToken"] = token
    parametri["periodStart"] = PERIODO_INIZIO
    parametri["periodEnd"] = PERIODO_FINE
    tipo = parametri.pop("documentType")

    descrizione = " ".join("%s=%s" % (k, v) for k, v in parametri.items()
                           if k in ("in_Domain", "out_Domain", "in_Domain",
                                    "outBiddingZone_Domain", "inBiddingZone_Domain"))
    print("[%s] %s | %s" % (MARCHIO, etichetta, descrizione))

    try:
        risposta = requests.get(INDIRIZZO, params=parametri, timeout=60)
    except Exception as errore:
        print("     ERRORE di rete:", type(errore).__name__, errore)
        return None

    print("     HTTP", risposta.status_code, "| dimensione risposta:",
          len(risposta.content), "byte")
    try:
        radice = ET.fromstring(risposta.content)
    except ET.ParseError:
        print("     la risposta NON e' XML valido. Prime righe:")
        print("     ", risposta.text.strip().replace("\n", " ")[:200])
        return None

    tipo_documento = senza_namespace(radice.tag)
    print("     tipo documento ricevuto:", tipo_documento)

    if "Acknowledgement" in tipo_documento:
        for motivo in motivi(radice):
            print("     RIFIUTATO da ENTSO-E:", motivo)
        return False

    serie = discendenti(radice, "TimeSeries")
    punti = discendenti(radice, "Point")
    print("     TimeSeries:", len(serie), "| Point totali:", len(punti))

    risoluzioni = sorted({(testo_di(p, "resolution") or "?")
                          for p in discendenti(radice, "Period")})
    if risoluzioni:
        print("     risoluzioni:", risoluzioni)

    if serie:
        print("     dettaglio delle prime TimeSeries (tipo impianto -> n. punti):")
        for una in serie[:10]:
            codici = [t.text for t in discendenti(una, "psrType")]
            nome_codice = ", ".join("%s (%s)" % (c, NOMI_PSR.get(c.strip(), "?"))
                                    for c in codici if c) or "-"
            quanti = len(discendenti(una, "Point"))
            print("       %-28s %d punti" % (nome_codice, quanti))

    if punti:
        file_xml = os.path.join(CARTELLA_LOG, "09_prova_%s_%s.xml" % (etichetta, MARCHIO))
        with open(file_xml, "w", encoding="utf-8") as file:
            file.write(nascondi(risposta.text))
        print("     salvato:", os.path.basename(file_xml))
        return True

    print("     risposta valida ma SENZA dati")
    return False


def principale():
    print("=== AVVIO", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "===")
    print("Resoconto:", FILE_ESITO)
    print("Finestra provata:", INIZIO_LOCALE.strftime("%d/%m %H:%M"),
          "->", FINE_LOCALE.strftime("%d/%m %H:%M"), "ora italiana")
    print("                 ", PERIODO_INIZIO, "->", PERIODO_FINE, "in UTC")
    print()

    segreti = leggi_segreti(PERCORSO)
    SEGRETI.update(segreti)
    token = segreti.get(NOME_SEGRETO, "")
    print("Token letto:", len(token), "caratteri")
    if len(token) != 36:
        print("Il token non ha la forma giusta (36 caratteri). Interrompo.")
        return
    print()

    nonna = "10Y1001A1001A73I"      # IT Nord
    sud = ZONE["IT Sud"]
    sicilia = ZONE["IT Sicilia"]
    calabria = ZONE["IT Calabria"]
    centro_sud = ZONE["IT Centro-Sud"]

    esperimenti = []

    # A65 - carico totale effettivo (domanda). Due modi possibili di indicare la zona.
    for etichetta, zona in [("A65_NORD_out", nonna), ("A65_SUD_out", sud)]:
        esperimenti.append((etichetta, {"documentType": "A65", "processType": "A16",
                                        "outBiddingZone_Domain": zona,
                                        "periodStart": PERIODO_INIZIO,
                                        "periodEnd": PERIODO_FINE}))
    esperimenti.append(("A65_SUD_in", {"documentType": "A65", "processType": "A16",
                                       "in_Domain": sud,
                                       "periodStart": PERIODO_INIZIO,
                                       "periodEnd": PERIODO_FINE}))

    # A75 - generazione effettiva per tipo di impianto.
    esperimenti.append(("A75_SUD_in", {"documentType": "A75", "processType": "A16",
                                       "in_Domain": sud,
                                       "periodStart": PERIODO_INIZIO,
                                       "periodEnd": PERIODO_FINE}))
    esperimenti.append(("A75_SUD_out", {"documentType": "A75", "processType": "A16",
                                        "outBiddingZone_Domain": sud,
                                        "periodStart": PERIODO_INIZIO,
                                        "periodEnd": PERIODO_FINE}))
    esperimenti.append(("A75_NORD_in", {"documentType": "A75", "processType": "A16",
                                        "in_Domain": nonna,
                                        "periodStart": PERIODO_INIZIO,
                                        "periodEnd": PERIODO_FINE}))

    # A11 - flussi fisici fra due zone italiane.
    esperimenti.append(("A11_SUD_verso_CSUD", {"documentType": "A11",
                                               "out_Domain": sud, "in_Domain": centro_sud,
                                               "periodStart": PERIODO_INIZIO,
                                               "periodEnd": PERIODO_FINE}))
    esperimenti.append(("A11_SIC_verso_CALA", {"documentType": "A11",
                                               "out_Domain": sicilia, "in_Domain": calabria,
                                               "periodStart": PERIODO_INIZIO,
                                               "periodEnd": PERIODO_FINE}))

    # Indisponibilita' (rete e impianti): quali documenti esistono.
    for codice in ["A77", "A78", "A79", "A80"]:
        esperimenti.append(("PROVA_%s_SUD" % codice,
                            {"documentType": codice, "in_Domain": sud,
                             "periodStart": PERIODO_INIZIO,
                             "periodEnd": PERIODO_FINE}))

    esiti = {}
    for etichetta, parametri in esperimenti:
        esito = prova(token, etichetta, parametri)
        esiti[etichetta] = esito
        print()

    print("=== SINTESI ===")
    print("  %-22s %s" % ("prova", "risultato"))
    for etichetta, esito in esiti.items():
        if esito is True:
            testo = "DATI RICEVUTI"
        elif esito is False:
            esito = "risposta senza dati / rifiutata"
        else:
            esito = "errore"
        print("  %-28s %s" % (etichetta, esito))


SCHERMO = sys.stdout
RESOCONTO = Doppio(FILE_ESITO, SCHERMO)
sys.stdout = RESOCONTO

try:
    principale()
except Exception as errore:
    print("ERRORE:", type(errore).__name__, errore)
    print(traceback.format_exc())
else:
    print("FINE: esecuzione conclusa senza errori.")
finally:
    RESOCONTO.flush()
    RESOCONTO.file.close()
    sys.stdout = SCHERMO
