# 10_scarica_altro.py
#
# Scarica i dati che servono per spiegare il crollo del prezzo al Sud del 16/10:
#   A65  domanda (carico) per zona
#   A75  generazione effettiva per tipo di impianto, per zona
#   A44  prezzi day-ahead dei paesi vicini (per capire se il Sud esportava)
#
# PERCHE' PROVA PIU' COMBINAZIONI: ENTSO-E non valida i parametri uno per uno,
# valida la COMBINAZIONE. Lo script 09 ha mostrato che:
#   - A65/A75 con "processType=A16" -> "The combination of [PROCESS_TYPE=A16]
#     is not valid" (quindi il processo va indicato diversamente, o non va indicato)
#   - A11/A77/A78/A79/A80 -> "The combination of [] is not valid" (parametri obbligatori mancanti)
# Percio' qui prima SI PROVA (finestra breve di 1 giorno) e appena una variante
# risponde con dati, la si usa per scaricare tutto (finestra di 4 giorni).
#
# Cosa produce, in energy-data\log\ :
#   10_esito_<data_ora>.txt          il resoconto
#   10_A65_<zona>_<data_ora>.xml     domanda per zona
#   10_A75_<zona>_<data_ora>.xml     generazione per tipo, per zona
#   10_A44_<paese>_<data_ora>.xml    prezzi dei paesi vicini
# Gli XML vengono riletti dallo script 11: dopo questa esecuzione il volume NON
# serve piu'.
#
# Come si usa: montare il volume su A:, aprire questo file in IDLE, premere F5.

import os
import sys
import traceback
import xml.etree.ElementTree as ET
import zoneinfo
from datetime import datetime, timezone

import requests

PERCORSO = r"A:\secrets.env"
INDIRIZZO = "https://web-api.tp.entsoe.eu/api"
MASCHERA = "***SEGRETO-NASCOSTO***"
NOME_SEGRETO = "ENTSOE_TOKEN"

ROMA = zoneinfo.ZoneInfo("Europe/Rome")

# nome leggibile -> (codice breve, codice EIC)
ZONE = {
    "IT Nord":        ("NORD", "10Y1001A1001A73I"),
    "IT Centro-Nord": ("CNOR", "10Y1001A1001A70O"),
    "IT Centro-Sud":  ("CSUD", "10Y1001A1001A71M"),
    "IT Sud":         ("SUD",  "10Y1001A1001A788"),
    "IT Sicilia":     ("SICI", "10Y1001A1001A75E"),
    "IT Sardegna":    ("SARD", "10Y1001A1001A74G"),
    "IT Calabria":    ("CALA", "10Y1001C--00096J"),
}

# "10YIT-GRTN-----B" e' l'Italia come paese (serve se i dati per zona non esistono)
ITALIA = ("IT_CA", "10YIT-GRTN-----B")

VICINI = {
    "Grecia":     ("GR", "10YGR-HTSO-----Y"),
    "Francia":    ("FR", "10YFR-RTE------C"),
    "Austria":    ("AT", "10YAT-APG------L"),
    "Slovenia":   ("SI", "10YSI-ELES-----O"),
    "Svizzera":   ("CH", "10YCH-SWISSGRIDZ"),
    "Montenegro": ("ME", "10YCS-CG-TSO---S"),
}

NOMI_PSR = {
    "B01": "biomassa", "B02": "carbone bruno", "B03": "carbone", "B04": "gas",
    "B05": "olio", "B06": "olio", "B07": "olio", "B08": "torba",
    "B09": "geotermico", "B10": "idro pompaggio", "B11": "idro fluente",
    "B12": "idro serbatoio", "B13": "rifiuti", "B14": "nucleare", "B15": "altro",
    "B16": "solare", "B17": "altro", "B18": "eolico offshore",
    "B19": "eolico onshore", "B20": "altro",
}

PROVA_INIZIO = datetime(2026, 10, 16, 0, 0, tzinfo=ROMA)
PROVA_FINE = datetime(2026, 10, 17, 0, 0, tzinfo=ROMA)

SCARICO_INIZIO = datetime(2026, 10, 15, 0, 0, tzinfo=ROMA)
SCARICO_FINE = datetime(2026, 10, 19, 0, 0, tzinfo=ROMA)

CARTELLA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
os.makedirs(CARTELLA_LOG, exist_ok=True)
MARCHIO = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FILE_ESITO = os.path.join(CARTELLA_LOG, "10_esito_" + MARCHIO + ".txt")

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
        descrizione = testo_di(motivo, "text") or "?"
        elenco.append(codice + " - " + descrizione)
    return elenco


def chiedi(token, parametri, inizio_locale, fine_locale):
    invio = dict(parametri)
    invio["securityToken"] = token
    invio["periodStart"] = inizio_locale.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
    invio["periodEnd"] = fine_locale.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
    return requests.get(INDIRIZZO, params=invio, timeout=90)


def esamina(risposta, percorso_salvataggio=None):
    """Legge la risposta. Restituisce (ok, righe di resoconto)."""
    righe = ["     HTTP %s | %d byte" % (risposta.status_code, len(risposta.content))]
    try:
        radice = ET.fromstring(risposta.content)
    except ET.ParseError:
        righe.append("     NON e' XML valido. Prime righe: "
                     + risposta.text.strip().replace("\n", " ")[:200])
        return False, righe

    tipo = senza_namespace(radice.tag)
    righe.append("     tipo documento: " + tipo)
    if "Acknowledgement" in tipo:
        for motivo in motivi(radice):
            righe.append("     RIFIUTATO: " + motivo)
        return False, righe

    serie = discendenti(radice, "TimeSeries")
    punti = discendenti(radice, "Point")
    risoluzioni = sorted({(testo_di(p, "resolution") or "?")
                          for p in discendenti(radice, "Period")})
    codici = sorted({(t.text or "").strip() for t in discendenti(radice, "psrType")})

    righe.append("     TimeSeries: %d | Point: %d | risoluzioni: %s"
                 % (len(serie), len(punti), risoluzioni or "-"))
    if codici:
        righe.append("     tipi di impianto: " + ", ".join(
            "%s (%s)" % (c, NOMI_PSR.get(c, "?")) for c in codici))
    if not punti:
        righe.append("     risposta valida ma SENZA dati")
        return False, righe

    if percorso_salvataggio:
        with open(percorso_salvataggio, "w", encoding="utf-8") as file:
            file.write(nascondi(risposta.text))
        righe.append("     salvato: " + os.path.basename(percorso_salvataggio))
    return True, righe


def provatore(token, titolo, varianti, inizio, fine):
    """Prova le varianti; restituisce i parametri della prima che da' dati."""
    print(titolo)
    for etichetta, parametri in varianti:
        print("  variante '%s'" % etichetta)
        try:
            risposta = chiedi(token, parametri, inizio, fine)
        except Exception as errore:
            print("     ERRORE di rete:", type(errore).__name__, errore)
            continue
        ok, righe = esamina(risposta)
        for riga in righe:
            print(riga)
        if ok:
            print("  -> VARIANTE BUONA:", etichetta)
            print()
            return etichetta, parametri
    print("  -> nessuna variante accettata")
    print()
    return None, None


def scarica_gruppo(token, titolo, parametri_base, elenco, prefisso, inizio, fine):
    """Scarica la stessa cosa per un elenco di zone/paesi e salva gli XML."""
    print(titolo)
    riusciti = 0
    for nome, (breve, codice) in elenco.items():
        invio = dict(parametri_base)
        for chiave in ("outBiddingZone_Domain", "out_Domain", "in_Domain",
                       "inBiddingZone_Domain"):
            if chiave in invio:
                invio[chiave] = codice
        percorso = os.path.join(CARTELLA_LOG, "10_%s_%s_%s.xml" % (prefisso, breve, MARCHIO))
        print("  %-16s" % nome)
        try:
            risposta = chiedi(token, invio, inizio, fine)
        except Exception as errore:
            print("     ERRORE di rete:", type(errore).__name__, errore)
            continue
        ok, righe = esamina(risposta, percorso)
        for riga in righe:
            print(riga)
        if ok:
            riusciti += 1
    print("  -> scaricati %d su %d" % (riusciti, len(elenco)))
    print()
    return riusciti


def principale():
    print("=== AVVIO", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "===")
    print("Resoconto:", FILE_ESITO)
    print("Prova parametri : 16/10 00:00 -> 17/10 00:00 ora italiana")
    print("Scarico vero    : 15/10 00:00 -> 19/10 00:00 ora italiana")
    print()

    segreti = leggi_segreti(PERCORSO)
    SEGRETI.update(segreti)
    token = segreti.get(NOME_SEGRETO, "")
    print("Token letto:", len(token), "caratteri")
    if len(token) != 36:
        print("Token non valido. Interrompo.")
        return
    print()

    sud = ZONE["IT Sud"][1]

    # ---- FASE 1: carico per zona (A65) -------------------------------------
    print("############ FASE 1 - carico (A65), prova sul Sud ############")
    varianti_carico = [
        ("solo outBiddingZone_Domain",
         {"documentType": "A65", "outBiddingZone_Domain": sud}),
        ("outBiddingZone_Domain + out_Domain",
         {"documentType": "A65", "outBiddingZone_Domain": sud, "out_Domain": sud}),
        ("processType A16 + outBiddingZone_Domain + out_Domain",
         {"documentType": "A65", "processType": "A16",
          "outBiddingZone_Domain": sud, "out_Domain": sud}),
        ("solo in_Domain",
         {"documentType": "A65", "in_Domain": sud}),
    ]
    carico = provatore(token, "Varianti A65 provate (zona IT Sud):",
                       varianti_carico, PROVA_INIZIO, PROVA_FINE)

    # ---- FASE 2: generazione per tipo (A75) --------------------------------
    print("############ FASE 2 - generazione per tipo (A75), prova sul Sud ############")
    varianti_generazione = [
        ("processType A16 + in_Domain",
         {"documentType": "A75", "processType": "A16", "in_Domain": sud}),
        ("solo in_Domain",
         {"documentType": "A75", "in_Domain": sud}),
        ("solo outBiddingZone_Domain",
         {"documentType": "A75", "outBiddingZone_Domain": sud}),
        ("in_Domain + outBiddingZone_Domain",
         {"documentType": "A75", "in_Domain": sud, "outBiddingZone_Domain": sud}),
        ("in_Domain + out_Domain",
         {"documentType": "A75", "in_Domain": sud, "out_Domain": sud}),
        ("in_Domain + psrType B16",
         {"documentType": "A75", "in_Domain": sud, "psrType": "B16"}),
    ]
    generazione = provatore(token, "Varianti A75 provate (zona IT Sud):",
                            varianti_generazione, PROVA_INIZIO, PROVA_FINE)
    # se ha funzionato solo la variante "con psrType" (solo solare), provo a
    # togliere il filtro: ci serve anche l'eolico, e' il sospetto principale
    if generazione[1] is not None and "psrType" in generazione[1]:
        print("La variante buona filtra un solo tipo di impianto: provo a togliere il filtro.")
        senza_filtro = {k: v for k, v in generazione[1].items() if k != "psrType"}
        risposta = chiedi(token, senza_filtro, PROVA_INIZIO, PROVA_FINE)
        ok, righe = esamina(risposta)
        for riga in righe:
            print("  " + riga)
        if ok:
            generazione = ("in_Domain senza filtro psrType", senza_filtro)
            print("  -> uso la variante senza filtro (tutti i tipi di impianto)")
        print()

    # ---- FASE 3: scarico vero del carico -----------------------------------
    print("############ FASE 3 - carico per tutte le zone ############")
    zone_caricate = 0
    if carico[1] is not None:
        zone_caricate = scarica_gruppo(token, "Carico (A65) per zona:",
                                       carico[1], ZONE, "A65", SCARICO_INIZIO, SCARICO_FINE)
    else:
        print("  salto: nessuna variante A65 funzionante")
        print()

    # ---- FASE 4: scarico vero della generazione ---------------------------
    print("############ FASE 4 - generazione per tipo, per zona ############")
    zone_generazione = 0
    if generazione[1] is not None:
        zone_generazione = scarica_gruppo(token, "Generazione (A75) per zona:",
                                          generazione[1], ZONE, "A75",
                                          SCARICO_INIZIO, SCARICO_FINE)
        if zone_generazione < len(ZONE):
            print("  alcune zone non hanno risposto: provo il livello Italia")
            scarica_gruppo(token, "Generazione (A75) Italia come paese:",
                           generazione[1], {"Italia": ITALIA}, "A75",
                           SCARICO_INIZIO, SCARICO_FINE)
    else:
        print("  generazione per zona NON disponibile con queste varianti:")
        print("  provo l'Italia intera con la variante piu' promettente")
        variante_italia = dict(varianti_generazione[1][1])
        variante_italia["in_Domain"] = ITALIA[1]
        risposta = chiedi(token, variante_italia, PROVA_INIZIO, PROVA_FINE)
        ok, righe = esamina(risposta)
        for riga in righe:
            print("  " + riga)
        if ok:
            scarica_gruppo(token, "Generazione (A75) Italia:",
                           variante_italia, {"Italia": ITALIA}, "A75",
                           SCARICO_INIZIO, SCARICO_FINE)
        print()

    # ---- FASE 5: prezzi dei paesi vicini (A44) ----------------------------
    print("############ FASE 5 - prezzi day-ahead dei paesi vicini (A44) ############")
    capi = []
    for nome, (breve, codice) in VICINI.items():
        capi.append((nome, breve, codice))
    riusciti = 0
    for nome, breve, codice in capi:
        parametri = {"documentType": "A44", "in_Domain": codice, "out_Domain": codice}
        percorso = os.path.join(CARTELLA_LOG, "10_A44_%s_%s.xml" % (breve, MARCHIO))
        print("  %-12s" % nome)
        try:
            risposta = chiedi(token, parametri, SCARICO_INIZIO, SCARICO_FINE)
        except Exception as errore:
            print("     ERRORE di rete:", type(errore).__name__, errore)
            continue
        ok, righe = esamina(risposta, percorso)
        for riga in righe:
            print(riga)
        if ok:
            riusciti += 1
    print("  -> scaricati %d su %d" % (riusciti, len(capi)))
    print()

    # ---- FASE 6: proviamo flussi e indisponibilita' -----------------------
    print("############ FASE 6 - tentativi su flussi (A11) e indisponibilita' ############")
    centro_sud = ZONE["IT Centro-Sud"][1]
    tentativi = [
        ("A11 sud->centrosud", {"documentType": "A11", "out_Domain": sud,
                                "in_Domain": centro_sud}),
        ("A11 centosud->sud", {"documentType": "A11", "out_Domain": centro_sud,
                               "in_Domain": sud}),
        ("A11 con businessType A01", {"documentType": "A11", "out_Domain": sud,
                                      "in_Domain": centro_sud, "businessType": "A01"}),
        ("A78 in_Domain", {"documentType": "A78", "in_Domain": sud}),
        ("A78 con businessType A53", {"documentType": "A78", "in_Domain": sud,
                                      "businessType": "A53"}),
        ("A80 in_Domain", {"documentType": "A80", "in_Domain": sud}),
        ("A77 in_Domain", {"documentType": "A77", "in_Domain": sud}),
    ]
    for etichetta, parametri in tentativi:
        print("  %s" % etichetta)
        try:
            risposta = chiedi(token, parametri, PROVA_INIZIO, PROVA_FINE)
        except Exception as errore:
            print("     ERRORE di rete:", type(errore).__name__, errore)
            continue
        ok, righe = esamina(risposta)
        for riga in righe:
            print(riga)
    print()

    # ---- RIEPILOGO -------------------------------------------------------
    print("=== RIEPILOGO ===")
    print("  A65 carico       : variante = %s | zone scaricate: %d su %d"
          % (carico[0] or "nessuna", zone_caricate, len(ZONE)))
    print("  A75 generazione  : variante = %s | zone scaricate: %d su %d"
          % (generazione[0] or "nessuna", zone_generazione, len(ZONE)))
    print("  A44 prezzi vicini: %d su %d" % (riusciti, len(VICINI)))
    print()
    print("Nota: gli XML 10_*.xml sono la risposta grezza di ENTSO-E. Lo script 11")
    print("li leggera' per fare i conti, senza bisogno del volume.")


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
