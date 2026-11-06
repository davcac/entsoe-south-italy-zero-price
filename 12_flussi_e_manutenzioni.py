# 12_flussi_e_manutenzioni.py
#
# Terzo e ultimo scarico da ENTSO-E (serve il volume montato su A:).
# Obiettivo: misurare il tetto del corridoio Sud -> Centro-Sud e controllare
# se il 16/10 c'erano linee in manutenzione.
#
# Scarica:
#   A11  flussi fisici reali fra zone confinanti (Sud/Centro-Sud, Calabria,
#        Sicilia, e verso l'estero: Grecia, Montenegro, Malta)
#   A78  indisponibilita' della rete di trasmissione (arriva COMPRESSO in .zip)
#   A80  indisponibilita' degli impianti di produzione (per il Sud e dintorni,
#        spezzato in finestre corte perche' ENTSO-E limita il numero di record)
#   A68  capacita' installata per tipo (prova: serve per sapere "quanto e' tanto"
#        2.300 MW di vento al Sud)
#
# Produce in energy-data\log\ :
#   12_esito_<data_ora>.txt
#   12_A11_<coppia>_<data_ora>.xml
#   12_A78_<data_ora>.zip  e  12_A78_<data_ora>_<n>.xml (estratto)
#   12_A80_<zona>_<data_ora>.xml
#   12_A68_<zona>_<data_ora>.xml
#
# Come si usa: montare il volume su A:, aprire in IDLE, premere F5.

import io
import os
import sys
import traceback
import xml.etree.ElementTree as ET
import zipfile
import zoneinfo
from datetime import datetime, timedelta, timezone

import requests

PERCORSO = r"A:\secrets.env"
INDIRIZZO = "https://web-api.tp.entsoe.eu/api"
MASCHERA = "***SEGRETO-NASCOSTO***"
NOME_SEGRETO = "ENTSOE_TOKEN"

ROMA = zoneinfo.ZoneInfo("Europe/Rome")
CARTELLA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
os.makedirs(CARTELLA_LOG, exist_ok=True)
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_ESITO = os.path.join(CARTELLA_LOG, "12_esito_" + MARCHIO + ".txt")

EIC = {
    "SUD":  "10Y1001A1001A788",
    "CSUD": "10Y1001A1001A71M",
    "CALA": "10Y1001C--00096J",
    "SICI": "10Y1001A1001A75E",
    "GR":   "10YGR-HTSO-----Y",
    "ME":   "10YCS-CG-TSO---S",
    "MT":   "10Y1001A1001A93C",
}

# coppie di confini da scaricare (documento A11): (etichetta, da, verso)
BORDI = [
    ("SUD_CSUD", "SUD", "CSUD"),
    ("CSUD_SUD", "CSUD", "SUD"),
    ("SUD_CALA", "SUD", "CALA"),
    ("CALA_SUD", "CALA", "SUD"),
    ("CALA_SICI", "CALA", "SICI"),
    ("SICI_CALA", "SICI", "CALA"),
    ("SUD_GR", "SUD", "GR"),
    ("GR_SUD", "GR", "SUD"),
    ("SUD_ME", "SUD", "ME"),
    ("ME_SUD", "ME", "SUD"),
    ("SICI_MT", "SICI", "MT"),
    ("MT_SICI", "MT", "SICI"),
]

# zone per cui cercare indisponibilita' degli impianti (A80)
ZONE_A80 = [("SUD", EIC["SUD"]), ("CALA", EIC["CALA"]), ("SICI", EIC["SICI"])]

FINESTRA_INIZIO = datetime(2026, 10, 15, 0, 0, tzinfo=ROMA)
FINESTRA_FINE = datetime(2026, 10, 19, 0, 0, tzinfo=ROMA)

# le indisponibilita' si cercano solo intorno ai due mezzogiorni che ci interessano
A80_GIORNI = ["2026-10-16", "2026-10-17"]
A80_ORA_INIZIO = 8
A80_ORA_FINE = 18
A80_PASSO_ORE = 3

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


def chiedi(token, parametri, inizio_locale, fine_locale):
    invio = dict(parametri)
    invio["securityToken"] = token
    invio["periodStart"] = inizio_locale.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
    invio["periodEnd"] = fine_locale.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
    return requests.get(INDIRIZZO, params=invio, timeout=120)


def esamina(risposta):
    """Restituisce (ok, motivo, righe) su una risposta XML."""
    righe = ["     HTTP %s | %d byte" % (risposta.status_code, len(risposta.content))]
    motivo = ""
    try:
        radice = ET.fromstring(risposta.content)
    except ET.ParseError:
        righe.append("     NON e' XML valido: " + risposta.text.strip()[:160])
        return False, "non-xml", righe, None

    tipo = senza_namespace(radice.tag)
    righe.append("     tipo documento: " + tipo)
    if "Acknowledgement" in tipo:
        for motivo_el in discendenti(radice, "Reason"):
            codice = testo_di(motivo_el, "code") or "?"
            descrizione = testo_di(motivo_el, "text") or "?"
            motivo = codice + " - " + descrizione
            righe.append("     RIFIUTATO: " + motivo)
        return False, motivo, righe, radice

    serie = discendenti(radice, "TimeSeries")
    punti = discendenti(radice, "Point")
    righe.append("     TimeSeries: %d | Point: %d" % (len(serie), len(punti)))
    return len(punti) > 0, motivo, righe, radice


def salva_testo(percorso, risposta):
    with open(percorso, "w", encoding="utf-8") as file:
        file.write(nascondi(risposta.text))


def scarica_serie(token, titolo, parametri, inizio, fine, prefisso, etichetta):
    print("  %-14s" % titolo)
    try:
        risposta = chiedi(token, parametri, inizio, fine)
    except Exception as errore:
        print("     ERRORE di rete:", type(errore).__name__, errore)
        return 0
    ok, motivo, righe, radice = esamina(risposta)
    for riga in righe:
        print(riga)
    if ok:
        nome = "12_%s_%s_%s.xml" % (prefisso, etichetta, MARCHIO)
        salva_testo(os.path.join(CARTELLA_LOG, nome), risposta)
        return 1
    return 0


def fase_a11(token):
    print("############ FASE 1 - flussi fisici reali (A11) ############")
    print("  finestra: 15/10 00:00 -> 19/10 00:00 ora italiana")
    totale = 0
    for etichetta, da, verso in BORDI:
        parametri = {"documentType": "A11",
                     "out_Domain": EIC[da], "in_Domain": EIC[verso]}
        totale += scarica_serie(token, "%s -> %s" % (da, verso), parametri,
                                FINESTRA_INIZIO, FINESTRA_FINE, "A11", etichetta)
    print("  -> salvati %d file su %d" % (totale, len(BORDI)))
    print()


def fase_a78(token):
    print("############ FASE 2 - manutenzioni della rete (A78) ############")
    parametri = {"documentType": "A78", "in_Domain": EIC["SUD"]}
    try:
        risposta = chiedi(token, parametri, FINESTRA_INIZIO, FINESTRA_FINE)
    except Exception as errore:
        print("  ERRORE di rete:", type(errore).__name__, errore)
        print()
        return
    print("  HTTP %s | %d byte" % (risposta.status_code, len(risposta.content)))

    inizio_contenuto = risposta.content[:2]
    if inizio_contenuto == b"PK":
        percorso_zip = os.path.join(CARTELLA_LOG, "12_A78_%s.zip" % MARCHIO)
        with open(percorso_zip, "wb") as file:
            file.write(risposta.content)
        print("  salvato (compresso):", os.path.basename(percorso_zip))
        try:
            archivio = zipfile.ZipFile(io.BytesIO(risposta.content))
            for indice, nome_interno in enumerate(archivio.namelist(), start=1):
                dati = archivio.read(nome_interno)
                percorso_xml = os.path.join(CARTELLA_LOG,
                                            "12_A78_%s_%d.xml" % (MARCHIO, indice))
                with open(percorso_xml, "wb") as file:
                    file.write(dati)
                print("  dentro lo zip: %s | %d byte" % (nome_interno, len(dati)))
                print("     estratto in:", os.path.basename(percorso_xml))
                try:
                    radice = ET.fromstring(dati)
                except ET.ParseError:
                    print("     (non e' XML leggibile)")
                    continue
                print("     tipo documento:", senza_namespace(radice.tag))
                serie = discendenti(radice, "TimeSeries")
                print("     TimeSeries:", len(serie))
                if serie:
                    nomi = sorted({senza_namespace(f.tag) for f in list(serie[0])})
                    print("     campi di ogni TimeSeries:", ", ".join(nomi))
                    print("     mRID della prima:", testo_di(serie[0], "mRID"))
                    for campo in ("name", "asset_RegisteredResource.name"):
                        valore = testo_di(serie[0], campo)
                        if valore:
                            print("     %s: %s" % (campo, valore))
        except zipfile.BadZipFile:
            print("  lo zip non e' leggibile come archivio")
    else:
        ok, motivo, righe, radice = esamina(risposta)
        for riga in righe:
            print(riga)
        if ok:
            percorso = os.path.join(CARTELLA_LOG, "12_A78_%s.xml" % MARCHIO)
            salva_testo(percorso, risposta)
            print("  salvato:", os.path.basename(percorso))
    print()


def a80_finestre():
    """Le finestre di 3 ore su cui spezzare la ricerca delle indisponibilita'."""
    elenco = []
    for giorno in A80_GIORNI:
        for ora in range(A80_ORA_INIZIO, A80_ORA_FINE, A80_PASSO_ORE):
            inizio = datetime.fromisoformat("%sT%02d:00:00" % (giorno, ora)).replace(tzinfo=ROMA)
            fine = inizio + timedelta(hours=A80_PASSO_ORE)
            elenco.append((inizio, fine))
    return elenco


def fase_a80(token):
    print("############ FASE 3 - indisponibilita' degli impianti (A80) ############")
    print("  finestre di %d ore, 08:00-18:00 del 16 e 17 ottobre" % A80_PASSO_ORE)
    salvati = 0
    for etichetta, codice in ZONE_A80:
        print("  zona %s" % etichetta)
        for indice, (inizio, fine) in enumerate(a80_finestre(), start=1):
            parametri = {"documentType": "A80", "in_Domain": codice}
            nome = "12_A80_%s_%s_%02d" % (etichetta, MARCHIO, indice)
            print("    %s %s-%s" % (inizio.strftime("%d/%m %H:%M"),
                                    inizio.strftime("%H:%M"), fine.strftime("%H:%M")))
            try:
                risposta = chiedi(token, parametri, inizio, fine)
            except Exception as errore:
                print("     ERRORE di rete:", type(errore).__name__, errore)
                continue
            ok, motivo, righe, radice = esamina(risposta)
            for riga in righe:
                print(riga)
            if ok:
                percorso = os.path.join(CARTELLA_LOG, nome + ".xml")
                salva_testo(percorso, risposta)
                salvati += 1
            elif "xceed" in motivo or "too many" in motivo.lower():
                print("     (troppi record in %d ore: la finestra va accorciata)" % A80_PASSO_ORE)
    print("  -> salvati %d file" % salvati)
    print()


def fase_a68(token):
    print("############ FASE 4 - capacita' installata per zona (A68), prova ############")
    sud = EIC["SUD"]
    varianti = [
        ("processType A33", {"documentType": "A68", "processType": "A33",
                             "in_Domain": sud}),
        ("processType A16", {"documentType": "A68", "processType": "A16",
                             "in_Domain": EIC["SUD"]}),
        ("senza processType", {"documentType": "A68", "in_Domain": EIC["SUD"]}),
    ]
    buona = None
    for etichetta, parametri in varianti:
        print("  variante '%s'" % etichetta)
        try:
            risposta = chiedi(token, parametri, FINESTRA_INIZIO, FINESTRA_FINE)
        except Exception as errore:
            print("     ERRORE di rete:", type(errore).__name__, errore)
            continue
        ok, motivo, righe, radice = esamina(risposta)
        for riga in righe:
            print(riga)
        if ok:
            print("  -> variante buona:", etichetta)
            buona = parametri
            break
    if buona is None:
        print("  nessuna variante accettata: la capacita' installata non e' disponibile cosi'")
        print()
        return
    for etichetta, codice in ZONE_A80:
        parametri = dict(buona)
        parametri["in_Domain"] = codice
        scarica_serie(token, etichetta, parametri, FINESTRA_INIZIO, FINESTRA_FINE,
                      "A68", etichetta)
    print()


def principale():
    print("=== AVVIO", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "===")
    print("Resoconto:", FILE_ESITO)
    print()

    segreti = leggi_segreti(PERCORSO)
    SEGRETI.update(segreti)
    token = segreti.get(NOME_SEGRETO, "")
    print("Token letto:", len(token), "caratteri")
    if len(token) != 36:
        print("Token non valido. Interrompo.")
        return
    print()

    fase_a11(token)
    fase_a78(token)
    fase_a80(token)
    fase_a68(token)

    print("=== RIEPILOGO ===")
    print("  flussi A11   : %d coppie di confini" % len(BORDI))
    print("  manutenzioni : file 12_A78_%s.zip (+ XML estratti)" % MARCHIO)
    print("  impianti A80 : 3 zone x 2 giorni x finestre da %d ore" % A80_PASSO_ORE)
    print("=== FINE ===")


SCHERMO = sys.stdout
DOPPIO = Doppio(FILE_ESITO, SCHERMO)
sys.stdout = DOPPIO
try:
    principale()
except Exception:
    traceback.print_exc(file=DOPPIO)
finally:
    DOPPIO.flush()
    DOPPIO.file.close()
    sys.stdout = SCHERMO
