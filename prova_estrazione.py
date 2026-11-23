"""Confronta i modelli configurati sullo stesso testo, senza toccare il database.

Avvio:  python prova_estrazione.py [file di testo]
Senza argomenti usa esempi/nestle.txt (per le smentite: esempi/romania.txt) sul clone «carne_cavallo».
Prova ogni fornitore elencato in impostazioni.json (salta quelli cloud senza chiave)
e per ciascuno stampa le affermazioni proposte, gli avvisi dei controlli e il tempo.
"""

import sys
import time
from pathlib import Path

from core import extraction
from core.database import connect, read_profile

CLONE = "carne_cavallo"
path = Path(sys.argv[1] if len(sys.argv) > 1 else "esempi/nestle.txt")
text = path.read_text(encoding="utf-8")

conn = connect(CLONE)
profile = read_profile(CLONE)
known = [r[0] for r in conn.execute("SELECT label FROM entities ORDER BY label")]
print(f"Testo: {path} ({len(text)} caratteri)")

for name, conf in extraction.settings()["fornitori"].items():
    prov = extraction.provider(name)
    print(f"\n=== {extraction.describe(prov)} ===")
    if prov["tipo"] != "ollama" and not prov.get("chiave"):
        print("saltato: manca la chiave in impostazioni.json")
        continue
    start, total, clean = time.time(), 0, 0
    try:
        for chunk in extraction.chunks(text):
            claims = extraction.claims_for(conn, chunk) if extraction.about_relations(profile) else []
            result = extraction.ask_model(*extraction.build_prompt(profile, known, chunk, claims),
                                          extraction.response_schema(profile), prov)
            lines = []
            for raw in result.get("affermazioni", []):
                p, warnings = extraction.check(conn, profile, text, raw)
                total += 1
                clean += not warnings
                line = f"{p['soggetto']} — {p['relazione']} → {p['oggetto']}"
                lines.append((None, line))
                print(f"• {p['soggetto']} [{p['tipo_soggetto']}] — {p['relazione']} → "
                      f"{p['oggetto']} [{p['tipo_oggetto']}]  ({p['tipo_affermazione']}, {p['data'] or 'senza data'})")
                print(f"  «{p['estratto']}»")
                for w in warnings:
                    print(f"  ⚠ {w}")
            for raw in result.get("prese_di_posizione", []) or []:
                checked = extraction.check_about(conn, profile, chunk, raw, claims, lines)
                total += 1
                if not checked:
                    print(f"• {raw.get('soggetto')} — {raw.get('relazione')} → bersaglio inesistente "
                          f"«{raw.get('bersaglio')}» (scartata)")
                    continue
                p, warnings = checked
                clean += not warnings
                print(f"• {p['soggetto']} [{p['tipo_soggetto']}] — {p['relazione']} → [{p['bersaglio']}]"
                      f"  ({p['tipo_affermazione']}, {p['data'] or 'senza data'})")
                print(f"  «{p['estratto']}»")
                for w in warnings:
                    print(f"  ⚠ {w}")
    except (extraction.ModelError, ValueError) as e:
        print(f"ERRORE: {e}")
    print(f"-- {total} proposte, {clean} senza avvisi, {time.time() - start:.0f} secondi")
conn.close()
