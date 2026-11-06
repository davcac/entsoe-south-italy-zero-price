# 02_leggi_chiavi.py
#
# Legge le chiavi API dal volume cifrato VeraCrypt.
# REGOLA DI SICUREZZA: questo programma non stampa MAI il valore di una chiave.
# Stampa solo il NOME della chiave e quanti caratteri ha.
#
# Come si usa: aprire il volume su A:, aprire questo file in IDLE e premere F5.

import re

PERCORSO = r"A:\secrets.env"

def leggi_chiavi(percorso):
    chiavi = {}
    with open(percorso, "r", encoding="utf-8-sig") as file:
        for riga in file:
            riga = riga.strip()
            if not riga or riga.startswith("#"):
                continue
            m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", riga)
            if m:
                nome, valore = m.groups()
                chiavi[nome] = valore.strip().strip('"').strip("'")
    return chiavi

try:
    chiavi = leggi_chiavi(PERCORSO)
except FileNotFoundError:
    print("FILE NON TROVATO:", PERCORSO)
    print("Il volume e' montato? La lettera e' A:?")
except PermissionError:
    print("PERMESSO NEGATO:", PERCORSO)
else:
    print("Chiavi trovate in", PERCORSO, "->", len(chiavi))
    for nome, valore in chiavi.items():
        avviso = "   <-- SEGNAPOSTO: non e' un valore vero" if valore.startswith("METTI_QUI") else ""
        print("   ", nome, "->", len(valore), "caratteri", avviso)
