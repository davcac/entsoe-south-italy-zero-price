"""
01_api_basics_ecb.py
--------------------
Prima chiamata a un servizio web, lettura di XML e conversione in tabella.

Questo file NON usa API a pagamento e NON richiede chiavi: usa il file XML
dei cambi di riferimento della Banca Centrale Europea (aggiornato ogni
giorno lavorativo intorno alle 16:00).

Cosa fa, passo per passo:
  1. chiede il file XML al server della BCE
  2. controlla com'e' andata (codice HTTP: 200 = ok)
  3. trasforma il testo XML in un albero navigabile
  4. estrae i record (una ventina di valute)
  5. li mette in una tabella pandas
  6. converte i cambi da testo a numero e salva il tutto in CSV

Come si esegue:
  - da IDLE:  apri questo file e premi F5
  - da PowerShell 7:  python 01_api_basics_ecb.py
"""

import os

import pandas as pd
import requests
import xml.etree.ElementTree as ET

# La cartella in cui si trova questo script: cosi' il CSV finisce qui, sempre,
# anche se lanci il file da un'altra posizione.
CARTELLA = os.path.dirname(os.path.abspath(__file__))

URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


# --- 1. LA RICHIESTA --------------------------------------------------------
# requests.get(...) = "vai su internet e chiedi questo indirizzo".
# timeout=15 = "se il server non risponde entro 15 secondi, smetti di aspettare".
risposta = requests.get(URL, timeout=15)
print("1) codice HTTP:", risposta.status_code, "(200 = tutto ok)")

# --- 2. IL TESTO GREZZO -----------------------------------------------------
# In questo momento e' SOLO una stringa di testo: non e' ancora utilizzabile.
testo = risposta.text
print("2) caratteri ricevuti:", len(testo))

# --- 3. DA TESTO AD ALBERO --------------------------------------------------
# fromstring trasforma il testo XML in un albero di elementi navigabile.
radice = ET.fromstring(testo)
print("3) elemento radice:", radice.tag)

# --- 4. I RECORD ------------------------------------------------------------
# Il linguaggio di ricerca si legge cosi':
#   .//          = "ovunque qui sotto, in tutto l'albero"
#   {*}          = "di qualsiasi namespace" (il 'cognome' dell'elemento)
#   Cube         = il nome dell'elemento che cerco
#   [@currency]  = "solo quelli che hanno l'attributo currency"
record = radice.findall(".//{*}Cube[@currency]")
print("4) record trovati:", len(record))
print("   primo record:", record[0].attrib)

# --- 5. DA LISTA DI DIZIONARI A TABELLA -------------------------------------
# [r.attrib for r in record] = "per ogni r nella lista record, prendi r.attrib"
# Il risultato e' una lista di dizionari; pandas la trasforma in tabella.
tabella = pd.DataFrame([r.attrib for r in record])
print("5) tabella:", tabella.shape, "(righe, colonne)")

# --- 6. DA TESTO A NUMERO, E SALVATAGGIO ------------------------------------
# La colonna 'rate' arriva come TESTO: prima di fare calcoli va convertita.
tabella["rate"] = tabella["rate"].astype(float)

uscita = os.path.join(CARTELLA, "cambio_ecb.csv")
tabella.to_csv(uscita, index=False)  # index=False = non salvare la colonna 0,1,2...
print("6) salvato in:", uscita)

print()
print(tabella.head(10).to_string(index=False))
