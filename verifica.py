"""Verifica delle regole di MAVI. Avvio: python verifica.py

Ricrea i cloni di esempio, poi controlla che le regole funzionino davvero.
L'estrazione è provata con un modello simulato: non serve Ollama.
Stampa OK per ogni controllo superato; si ferma al primo che fallisce.
"""

import atexit
import json
import shutil
from pathlib import Path
import sqlite3
import subprocess
import sys

from core import extraction
from core.database import (add_assertion, add_entity, add_source, clone_dir,
                           connect, find_entity, graph)


def ok(msg):
    print("OK  ", msg)


# I controlli ricreano i cloni da zero: prima si mettono da parte i database esistenti,
# alla fine si rimettono al loro posto, così il lavoro fatto in revisione non va perso.
BACKUP = {}
for db in (Path(__file__).resolve().parent / "clones").glob("*/vault/context.db"):
    BACKUP[db] = db.read_bytes()


def restore():
    for db, data in BACKUP.items():
        db.write_bytes(data)


atexit.register(restore)   # anche se un controllo fallisce a metà


subprocess.run([sys.executable, "seed_modigliani.py"], check=True)
conn = connect("modigliani")
g = graph(conn)
edges = g["edges"]

# 1. Due assi distinti: tipo di affermazione e stato
types = {e["claim_type"] for e in edges}
assert types == {"documentato", "interpretazione", "ipotesi", "inferenza"}, types
ok("i quattro tipi di affermazione sono presenti e separati dallo stato")

# 2. Una relazione fuori catalogo viene rifiutata
try:
    add_assertion(conn, 1, "ha influenzato", 2, 1, claim_type="documentato")
    raise AssertionError("relazione fuori catalogo accettata")
except sqlite3.IntegrityError:
    conn.rollback()
ok("una relazione non prevista dalla scheda viene rifiutata")

# 3. Un tipo di entità fuori scheda viene rifiutato
try:
    add_entity(conn, "Black & Decker", "azienda")
    raise AssertionError("tipo di entità fuori scheda accettato")
except sqlite3.IntegrityError:
    conn.rollback()
ok("un tipo di entità non previsto dalla scheda viene rifiutato")

# 4. Gli alias portano alla stessa entità
assert find_entity(conn, "Fosso Mediceo") == find_entity(conn, "Fosso Reale")
assert find_entity(conn, "Vera Durbè") == find_entity(conn, "Vera Durbé")
ok("«Fosso Mediceo» e «Vera Durbè» portano alle entità giuste")

# 5. La storia della Testa 2 attribuita a Modigliani
t2 = next(e for e in edges if e["subject"] == "Testa 2" and e["object"] == "Amedeo Modigliani"
          and e["source_label"].startswith("Vera"))
assert [(h["status"], h["date"]) for h in t2["history"]] == [
    ("da_verificare", "1984-07-24"), ("smentita", "1984-09-03")], t2["history"]
ok("Testa 2 → Modigliani: da verificare il 24/7/1984, smentita il 3/9/1984")

# 6. Prima della confessione la Testa 2 non ha ancora altri autori noti
before = [e for e in edges if e["subject"] == "Testa 2" and e["relation"] == "è opera di"
          and e["known_from"] <= "1984-08-31"]
assert {e["object"] for e in before} == {"Amedeo Modigliani"}
ok("al 31 agosto 1984 l'unico autore attribuito alla Testa 2 è Modigliani")
conn.close()

# 7. Un nuovo clone nasce da una scheda, senza toccare il codice
PROVA = "_prova_verifica"
shutil.rmtree(clone_dir(PROVA), ignore_errors=True)
clone_dir(PROVA).mkdir(parents=True)
(clone_dir(PROVA) / "clone.json").write_text(json.dumps({
    "nome": "Prova", "dominio": "Qualsiasi", "obiettivo": "Verifica", "domande": [],
    "tipi_entita": ["azienda", "persona"],
    "relazioni": [{"nome": "dirige", "definizione": "Il soggetto guida l'organizzazione."}],
}), encoding="utf-8")
try:
    conn = connect(PROVA)
    s = add_source(conn, "Fonte di prova", date="2023-11-17")
    a = add_entity(conn, "Persona A", "persona")
    b = add_entity(conn, "Azienda B", "azienda")
    add_assertion(conn, a, "dirige", b, s, claim_type="documentato")
    conn.commit()
    assert len(graph(conn)["edges"]) == 1
    conn.close()
finally:
    shutil.rmtree(clone_dir(PROVA), ignore_errors=True)
ok("un clone di un dominio diverso funziona con la sola scheda")

# 8. Affermazioni su affermazioni (clone cibo)
subprocess.run([sys.executable, "seed_carne_cavallo.py"], check=True)
conn = connect("carne_cavallo")
edges = {e["id"]: e for e in graph(conn)["edges"]}
romania = next(e for e in edges.values() if e["object"] == "Romania")
assert [t["subject"] for t in romania["targeted_by"]] == ["Governo rumeno"]
smentita = edges[romania["targeted_by"][0]["id"]]
assert smentita["object_assertion_id"] == romania["id"]
ok("la smentita rumena punta proprio all'affermazione «la carne proviene dalla Romania»")

# 9. Ogni relazione accetta solo il tipo di oggetto dichiarato nella scheda
spanghero = find_entity(conn, "Spanghero")
try:  # «contesta» vuole un'affermazione, non un'entità
    add_assertion(conn, spanghero, "contesta", find_entity(conn, "Romania"), 1, claim_type="documentato")
    raise AssertionError("«contesta» accettata verso un'entità")
except sqlite3.IntegrityError:
    conn.rollback()
try:  # «fornisce» vuole un'entità, non un'affermazione
    add_assertion(conn, spanghero, "fornisce", None, 1, claim_type="documentato",
                  object_assertion_id=romania["id"])
    raise AssertionError("«fornisce» accettata verso un'affermazione")
except sqlite3.IntegrityError:
    conn.rollback()
ok("ogni relazione accetta solo il tipo di oggetto previsto dalla scheda")

try:  # «fornisce» va da azienda ad azienda, non verso una materia prima
    add_assertion(conn, spanghero, "fornisce", find_entity(conn, "Carne equina nelle lasagne"), 1,
                  claim_type="documentato")
    raise AssertionError("«fornisce» accettata verso una materia prima")
except sqlite3.IntegrityError:
    conn.rollback()
from core.database import read_profile
_, w = extraction.check(conn, read_profile("carne_cavallo"), "x", {
    "soggetto": "H.J. Schypke", "tipo_soggetto": "azienda", "relazione": "fornisce",
    "oggetto": "carne bovina", "tipo_oggetto": "materia prima", "tipo_affermazione": "documentato",
    "estratto": "x"})
assert any("vuole come oggetto azienda" in x for x in w), w
ok("soggetto e oggetto devono avere i tipi previsti dalla relazione (es. «fornisce»: azienda → azienda)")

# 10. Si sa chi sostiene ogni tesi, non solo chi la contesta
polonia = next(e for e in edges.values() if e["object"] == "Polonia")
assert [v["label"] for v in polonia["speakers"]] == ["Simon Coveney"]
assert [t["subject"] for t in polonia["targeted_by"]] == ["Jaroslaw Naze"]
ok("origine polacca: la sostiene Simon Coveney, la contesta Jaroslaw Naze")
conn.close()

# 11. Una fonte può avere più voci
conn = connect("modigliani")
t1 = next(e for e in graph(conn)["edges"]
          if e["subject"] == "Testa 1" and e["object"] == "Amedeo Modigliani")
assert {v["label"] for v in t1["speakers"]} == {"Vera Durbé", "Dario Durbé"}
ok("l'attribuzione della Testa 1 a Modigliani la sostengono Vera e Dario Durbé")
conn.close()

# 12-14. Estrazione e coda di revisione, con un modello simulato
NESTLE = open("esempi/nestle.txt", encoding="utf-8").read()


def fake_model(system, user, schema):
    assert "venduto da" in system and "Tesco" in user      # la scheda e le entità note arrivano al modello
    return {"affermazioni": [
        {"soggetto": "Ravioli di manzo Buitoni", "tipo_soggetto": "prodotto", "relazione": "Venduto da",
         "oggetto": "Nestlé", "tipo_oggetto": "azienda", "tipo_affermazione": "documentato",
         "data": "2013-02-18", "estratto": "Nestlé ha annunciato il ritiro dai supermercati italiani "
                                           "e spagnoli dei Ravioli di manzo Buitoni"},
        {"soggetto": "Nestlé", "tipo_soggetto": "azienda", "relazione": "ritira",
         "oggetto": "Ravioli di manzo Buitoni", "tipo_oggetto": "prodotto", "tipo_affermazione": "documentato",
         "data": "2013-02-18", "estratto": "Il 18 febbraio 2013 Nestlé ha annunciato il ritiro"},
        {"soggetto": "H.J. Schypke", "tipo_soggetto": "azienda", "relazione": "fornisce",
         "oggetto": "Spanghero", "tipo_oggetto": "azienda", "tipo_affermazione": "documentato",
         "data": "", "estratto": "Schypke riforniva anche Spanghero"},
        {"soggetto": "tesco", "tipo_soggetto": "azienda", "relazione": "ritira",
         "oggetto": "Hamburger di manzo Tesco", "tipo_oggetto": "prodotto", "tipo_affermazione": "documentato",
         "data": "", "estratto": "Tesco ritira gli hamburger"},
        {"soggetto": "Nestlé", "tipo_soggetto": "azienda", "relazione": "ritira",
         "oggetto": "Ravioli di manzo Buitoni", "tipo_oggetto": "prodotto", "tipo_affermazione": "documentato",
         "data": "2013-02-18", "estratto": "Il 18 febbraio 2013 Nestlé ha annunciato il ritiro"},
    ]}


conn = connect("carne_cavallo")
n = extraction.extract(conn, "carne_cavallo", NESTLE, "Prova Nestlé", "comunicato", "2013-02-18",
                       speaker="Nestlé", speaker_type="azienda", ask=fake_model)
queue = {(p["data"]["soggetto"], p["data"]["oggetto"]): p for p in extraction.pending(conn)}
assert n == 4 and len(queue) == 4, (n, list(queue))
assert queue[("Ravioli di manzo Buitoni", "Nestlé")]["data"]["relazione"] == "venduto da"
assert any("invenzione" in w for w in queue[("H.J. Schypke", "Spanghero")]["warnings"])
assert any("già nel grafo" in w for w in queue[("Tesco", "Hamburger di manzo Tesco")]["warnings"])
ok("estrazione: doppioni tolti, nomi ricondotti alle entità note, invenzioni e ripetizioni segnalate")

ritiro = queue[("Nestlé", "Ravioli di manzo Buitoni")]
aid = extraction.approve(conn, ritiro["id"], ritiro["data"])
e = next(e for e in graph(conn)["edges"] if e["id"] == aid)
assert e["status"] == "da_verificare" and e["source_label"] == "Prova Nestlé"
assert [v["label"] for v in e["speakers"]] == ["Nestlé"]
ok("una proposta approvata entra nel grafo come «da verificare», con fonte e voce")

wrong = dict(queue[("Ravioli di manzo Buitoni", "Nestlé")]["data"], relazione="ha influenzato")
try:
    extraction.approve(conn, queue[("Ravioli di manzo Buitoni", "Nestlé")]["id"], wrong)
    raise AssertionError("approvata una relazione fuori scheda")
except ValueError:
    pass
extraction.reject(conn, queue[("H.J. Schypke", "Spanghero")]["id"])
assert len(extraction.pending(conn)) == 2
assert find_entity(conn, "H.J. Schypke") is None
ok("le correzioni fuori scheda sono rifiutate; una proposta scartata non lascia tracce nel grafo")
conn.close()


# 16. Date scritte in modi diversi
from core.database import normalize_date
assert [normalize_date(d) for d in ("20260917", "17/09/2026", "2026/9/17", "09/2026", "2013")] == \
    ["2026-09-17", "2026-09-17", "2026-09-17", "2026-09", "2013"]
for bad in ("17/13/2026", "ieri"):
    try:
        normalize_date(bad)
        raise AssertionError(f"data accettata: {bad}")
    except ValueError:
        pass
ok("le date 20260917, 17/09/2026, 2026/9/17 diventano 2026-09-17; quelle impossibili sono rifiutate")

# 17-18. La scheda cresce: relazioni nuove proposte dal modello, approvate o scartate
SCHEDA = "_prova_scheda"
shutil.rmtree(clone_dir(SCHEDA), ignore_errors=True)
clone_dir(SCHEDA).mkdir(parents=True)
shutil.copy(clone_dir("carne_cavallo") / "clone.json", clone_dir(SCHEDA) / "clone.json")
TESTO = ("Europol coordina l'Operazione Equus contro il traffico di cavalli. "
         "Tesco ritira gli Hamburger di manzo Tesco. I trafficanti falsificano i passaporti dei cavalli.")


def model_with_new_relations(system, user, schema):
    assert "nuove_relazioni" in schema["properties"]
    return {"affermazioni": [], "nuove_relazioni": [
        {"nome": "coordina", "definizione": "Il soggetto dirige un'operazione.", "da": ["istituzione"],
         "a": ["indagine"], "esempi": [
            {"soggetto": "Europol", "tipo_soggetto": "istituzione", "relazione": "coordina",
             "oggetto": "Operazione Equus", "tipo_oggetto": "indagine", "tipo_affermazione": "documentato",
             "data": "", "estratto": "Europol coordina l'Operazione Equus"}]},
        {"nome": "Ritira", "definizione": "doppione", "da": ["azienda"], "a": ["prodotto"], "esempi": [
            {"soggetto": "Tesco", "tipo_soggetto": "azienda", "relazione": "Ritira",
             "oggetto": "Hamburger di manzo Tesco", "tipo_oggetto": "prodotto",
             "tipo_affermazione": "documentato", "data": "", "estratto": "Tesco ritira gli Hamburger di manzo Tesco"}]},
        {"nome": "falsifica", "definizione": "Il soggetto contraffà un documento.", "da": ["persona"],
         "a": ["documento"], "esempi": [
            {"soggetto": "Trafficanti", "tipo_soggetto": "persona", "relazione": "falsifica",
             "oggetto": "Passaporti dei cavalli", "tipo_oggetto": "documento", "tipo_affermazione": "documentato",
             "data": "", "estratto": "I trafficanti falsificano i passaporti dei cavalli"}]},
    ]}


try:
    conn = connect(SCHEDA)
    extraction.extract(conn, SCHEDA, TESTO, "Prova Europol", date="17/09/2026", ask=model_with_new_relations)
    assert conn.execute("SELECT date FROM sources").fetchone()[0] == "2026-09-17"
    schema = {sp["data"]["nome"]: sp for sp in extraction.schema_pending(conn)}
    assert set(schema) == {"coordina", "falsifica"}, set(schema)      # «Ritira» esiste già: niente proposta
    queue = {p["data"]["oggetto"]: p for p in extraction.pending(conn)}
    assert queue["Hamburger di manzo Tesco"]["data"]["relazione"] == "ritira"
    assert any("In attesa" in w for w in queue["Operazione Equus"]["warnings"])
    try:
        extraction.approve(conn, queue["Operazione Equus"]["id"], queue["Operazione Equus"]["data"])
        raise AssertionError("approvato un esempio prima della sua relazione")
    except ValueError:
        pass
    ok("il modello propone relazioni nuove con esempi; quelle già esistenti diventano proposte normali")

    extraction.approve_relation(conn, SCHEDA, schema["coordina"]["id"], {
        "nome": "coordina indagine", "definizione": "Il soggetto dirige un'indagine.",
        "da": "istituzione", "a": "indagine"})
    from core.database import read_profile
    prof = read_profile(SCHEDA)
    assert "indagine" in prof["tipi_entita"]
    assert any(r["nome"] == "coordina indagine" and r["a"] == ["indagine"] for r in prof["relazioni"])
    ex = next(p for p in extraction.pending(conn) if p["data"]["oggetto"] == "Operazione Equus")
    assert ex["data"]["relazione"] == "coordina indagine" and not ex["warnings"], ex
    extraction.approve(conn, ex["id"], ex["data"])
    extraction.reject_relation(conn, schema["falsifica"]["id"])
    assert not any(p["data"]["oggetto"] == "Passaporti dei cavalli" for p in extraction.pending(conn))
    assert not any(r["nome"] == "falsifica" for r in read_profile(SCHEDA)["relazioni"])
    ok("una relazione approvata (anche rinominata) entra nella scheda con i tipi nuovi; una scartata porta via i suoi esempi")
    conn.close()
finally:
    shutil.rmtree(clone_dir(SCHEDA), ignore_errors=True)

# 19-20. Correzioni dal grafo: cambio di stato e ritiro
from core.database import change_status, retract
subprocess.run([sys.executable, "seed_carne_cavallo.py"], check=True, capture_output=True)
conn = connect("carne_cavallo")
edges = {e["id"]: e for e in graph(conn)["edges"]}
polonia = next(e for e in edges.values() if e["object"] == "Polonia")
try:
    change_status(conn, polonia["id"], "smentita", "2013-03", "")
    raise AssertionError("cambio di stato accettato senza motivo")
except ValueError:
    pass
change_status(conn, polonia["id"], "smentita", "03/2013", "Le analisi polacche non confermano l'origine.")
h = next(e for e in graph(conn)["edges"] if e["id"] == polonia["id"])["history"]
assert h[-1] == {"status": "smentita", "date": "2013-03",
                 "reason": "Le analisi polacche non confermano l'origine."}, h
ok("un cambio di stato richiede un motivo e resta nella storia con la sua data")

romania = next(e for e in edges.values() if e["object"] == "Romania")
try:
    retract(conn, romania["id"], "prova")
    raise AssertionError("ritirata un'affermazione che altre contestano")
except ValueError:
    pass
retract(conn, romania["targeted_by"][0]["id"], "Prova: smentita inserita per errore")
retract(conn, romania["id"], "Prova: la fonte non dice questo")
g = graph(conn)
assert romania["id"] not in {e["id"] for e in g["edges"]}
assert {r["id"] for r in g["retracted"]} >= {romania["id"]}
canada = next(e for e in g["edges"] if e["object"] == "Canada")
assert not canada["conflicts"]            # il conflitto con l'affermazione ritirata non compare più
assert conn.execute("SELECT retracted_reason FROM assertions WHERE id = ?",
                    (romania["id"],)).fetchone()[0] == "Prova: la fonte non dice questo"
ok("un'affermazione ritirata esce dal grafo ma resta nell'archivio; prima vanno ritirate quelle che la riguardano")
conn.close()

# 21. Più voci nello stesso testo: ogni affermazione con chi la dice
subprocess.run([sys.executable, "seed_carne_cavallo.py"], check=True, capture_output=True)
ARTICOLO = ("Secondo Europol la rete falsificava i passaporti. Come spiega Eva Rigonat, i Paesi UE non "
            "comunicano tra loro. Tesco ritira gli hamburger, scrive il giornale.")


def model_with_voices(system, user, schema):
    assert "voce" in schema["properties"]["affermazioni"]["items"]["properties"]
    base = {"tipo_affermazione": "interpretazione", "data": "", "relazione": "membro di",
            "tipo_soggetto": "persona", "tipo_oggetto": "istituzione"}
    return {"nuove_relazioni": [], "affermazioni": [
        dict(base, soggetto="Eva Rigonat", oggetto="Governo francese", voce="Eva Rigonat", tipo_voce="persona",
             estratto="Come spiega Eva Rigonat, i Paesi UE non comunicano tra loro"),
        dict(base, soggetto="Simon Coveney", oggetto="Governo francese", voce="eva rigonat", tipo_voce="persona",
             estratto="i Paesi UE non comunicano tra loro"),
        dict(base, soggetto="Benoît Hamon", oggetto="Governo irlandese", voce="Europol", tipo_voce="istituzione",
             estratto="Secondo Europol la rete falsificava i passaporti"),
        dict(base, relazione="ritira", soggetto="Tesco", tipo_soggetto="azienda", oggetto="Polpette IKEA",
             tipo_oggetto="prodotto", voce="", tipo_voce="", estratto="Tesco ritira gli hamburger"),
    ]}


conn = connect("carne_cavallo")
extraction.extract(conn, "carne_cavallo", ARTICOLO, "Il Fatto Alimentare", "articolo", "17/09/2026",
                   ask=model_with_voices)
ids = [extraction.approve(conn, p["id"], p["data"]) for p in extraction.pending(conn)]
edges = {e["id"]: e for e in graph(conn)["edges"]}
voices = [[v["label"] for v in edges[i]["speakers"]] for i in ids]
assert voices == [["Eva Rigonat"], ["Eva Rigonat"], ["Europol"], []], voices
assert edges[ids[0]]["source_id"] == edges[ids[1]]["source_id"]          # una sola citazione per voce
assert edges[ids[0]]["reported_in"] == "Il Fatto Alimentare"
assert edges[ids[0]]["source_label"] == "Eva Rigonat, in «Il Fatto Alimentare»"
assert edges[ids[3]]["source_label"] == "Il Fatto Alimentare" and not edges[ids[3]]["reported_in"]
ok("in un articolo ogni affermazione va a chi la dice (Rigonat, Europol), come citazione riportata nell'articolo")
conn.close()

# 22. Unione di entità doppie
from core.database import merge_entities
subprocess.run([sys.executable, "seed_carne_cavallo.py"], check=True, capture_output=True)
conn = connect("carne_cavallo")
tesco, doppione = find_entity(conn, "Tesco"), add_entity(conn, "Tesco Stores", "azienda")
aid = add_assertion(conn, doppione, "ritira", find_entity(conn, "Polpette IKEA"), 1, claim_type="documentato")
conn.commit()
for a, b in (("Romania", "Spanghero"), ("Tesco", "Hamburger di manzo Tesco")):
    try:                      # tipo incompatibile; entità collegate tra loro
        merge_entities(conn, find_entity(conn, a), find_entity(conn, b))
        raise AssertionError(f"unione accettata: {a} in {b}")
    except ValueError:
        pass
merge_entities(conn, doppione, tesco)
assert conn.execute("SELECT subject_id FROM assertions WHERE id = ?", (aid,)).fetchone()[0] == tesco
assert find_entity(conn, "Tesco Stores") == tesco
assert conn.execute("SELECT merged_label FROM entity_merges").fetchone()[0] == "Tesco Stores"
ok("un doppione si unisce all'altra entità e ne diventa un nome alternativo; unioni incoerenti rifiutate")
conn.close()

# 23. Un tipo di entità si aggiunge alla scheda anche da solo
TIPI = "_prova_tipi"
shutil.rmtree(clone_dir(TIPI), ignore_errors=True)
clone_dir(TIPI).mkdir(parents=True)
shutil.copy(clone_dir("carne_cavallo") / "clone.json", clone_dir(TIPI) / "clone.json")
try:
    conn = connect(TIPI)
    extraction.extract(conn, TIPI, "Foodwatch denuncia: Tesco ritira gli hamburger.", "Prova",
                       ask=lambda *a: {"nuove_relazioni": [], "affermazioni": [
                           {"soggetto": "Tesco", "tipo_soggetto": "azienda", "relazione": "ritira",
                            "oggetto": "Hamburger", "tipo_oggetto": "prodotto",
                            "tipo_affermazione": "documentato", "data": "", "voce": "Foodwatch",
                            "tipo_voce": "organizzazione", "estratto": "Tesco ritira gli hamburger"}]})
    assert extraction.pending(conn)[0]["warnings"]
    extraction.add_entity_type(conn, TIPI, "organizzazione")
    assert not extraction.pending(conn)[0]["warnings"]
    try:
        extraction.add_entity_type(conn, TIPI, "Organizzazione")
        raise AssertionError("tipo doppio accettato")
    except ValueError:
        pass
    conn.close()
finally:
    shutil.rmtree(clone_dir(TIPI), ignore_errors=True)
ok("un tipo nuovo si aggiunge alla scheda da solo e le proposte in attesa vengono ricontrollate")

# 24. Punti deboli del grafo
conn = connect("modigliani")
weak = {w["titolo"]: w["voci"] for w in graph(conn)["weak"]}
assert any("[1909]" in v["testo"] and "[1916]" in v["testo"] for v in weak["Conflitti aperti"])
assert "Contestazioni senza esito" not in weak     # nel clone Modigliani nessuna tesi è contestata
conn.close()
conn = connect("carne_cavallo")
weak = {w["titolo"]: w["voci"] for w in graph(conn)["weak"]}
assert any("Polonia" in v["testo"] for v in weak["Contestazioni senza esito"])
conn.close()
ok("i punti deboli emergono da soli: la leggenda 1909/1916 è un conflitto aperto, l'origine polacca è contestata")

# 25. Un clone nuovo nasce da una descrizione: scheda proposta dal modello, corretta, creata
from core.database import create_clone, list_clones, validate_profile


def model_profile(system, user, schema):
    assert "Gioconda" in user and "tipi_entita" in schema["properties"]
    return {"tipi_entita": ["persona", "opera", "luogo", "istituzione"], "relazioni": [
        {"nome": "ruba", "definizione": "Il soggetto sottrae l'opera.", "inversa": "rubata da",
         "da": ["persona"], "a": ["opera"]},
        {"nome": "custodisce", "definizione": "L'istituzione conserva l'opera.", "inversa": "custodita da",
         "da": ["istituzione"], "a": ["opera"]},
        {"nome": "nasconde in", "definizione": "Il soggetto tiene l'opera in un luogo.", "inversa": "",
         "da": ["persona"], "a": ["luogo", "edificio"]}]}


scheda = extraction.propose_profile("Il furto della Gioconda", "Arte · furti", "Ricostruire il furto del 1911.",
                                    ["Chi ha rubato il dipinto?"], ask=model_profile)
try:
    validate_profile(scheda)
    raise AssertionError("accettata una relazione con un tipo che non esiste")
except ValueError as e:
    assert "edificio" in str(e)
scheda["relazioni"][2]["a"] = ["luogo"]                     # la correzione della persona
slug = None
try:
    slug = create_clone("ZZ Prova Gioconda", scheda)
    assert slug == "zz_prova_gioconda"
    prof = read_profile(slug)
    assert [r["nome"] for r in prof["relazioni"]] == ["ruba", "custodisce", "nasconde in", "contesta"]
    assert slug in [c["nome"] for c in list_clones()]
    conn = connect(slug)
    assert graph(conn)["edges"] == []
    conn.close()
    try:
        create_clone("zz prova gioconda", scheda)
        raise AssertionError("creato due volte lo stesso clone")
    except ValueError:
        pass
finally:
    if slug:
        shutil.rmtree(clone_dir(slug), ignore_errors=True)
ok("un clone nuovo nasce da una descrizione: il modello propone la scheda, la persona la corregge, MAVI la crea")

# 26. Le prese di posizione si estraggono: bersagli nel grafo o nello stesso testo
subprocess.run([sys.executable, "seed_carne_cavallo.py"], check=True, capture_output=True)
conn = connect("carne_cavallo")
romania = conn.execute("""SELECT a.id FROM assertions a JOIN entities o ON o.id = a.object_id
                          WHERE a.relation = 'proviene da' AND o.label = 'Romania'""").fetchone()[0]
SMENTITE = ("Secondo il giornale, Spanghero fornisce Findus direttamente. Spanghero nega di fornire Findus "
            "direttamente. Comigel ribadisce che la carne non viene dalla Romania.")


def model_with_stances(system, user, schema):
    assert "prese_di_posizione" in schema["properties"] and f"A{romania}:" in user
    base = {"relazione": "contesta", "tipo_affermazione": "documentato", "data": "2013-02-12"}
    return {"nuove_relazioni": [], "affermazioni": [
        {"soggetto": "Spanghero", "tipo_soggetto": "azienda", "relazione": "fornisce", "oggetto": "Findus",
         "tipo_oggetto": "azienda", "tipo_affermazione": "interpretazione", "data": "", "voce": "",
         "tipo_voce": "", "estratto": "Spanghero fornisce Findus direttamente"}],
        "prese_di_posizione": [
            dict(base, soggetto="spanghero", tipo_soggetto="azienda", bersaglio="T1",
                 estratto="Spanghero nega di fornire Findus direttamente"),
            dict(base, soggetto="Comigel", tipo_soggetto="azienda", bersaglio=f"a{romania}",
                 estratto="Comigel ribadisce che la carne non viene dalla Romania"),
            dict(base, soggetto="Comigel", tipo_soggetto="azienda", bersaglio="A999999", estratto="x"),
            dict(base, soggetto="Comigel", tipo_soggetto="azienda", bersaglio="T7", estratto="x")]}


assert extraction.extract(conn, "carne_cavallo", SMENTITE, "Le Monde", "articolo", "2013-02-15",
                          ask=model_with_stances) == 3               # i bersagli inesistenti cadono
claim, on_text, on_graph = extraction.pending(conn)
assert on_text["data"]["bersaglio"] == "Spanghero — fornisce → Findus" and on_text["warnings"]
assert on_graph["data"]["bersaglio_affermazione"] == romania and not on_graph["warnings"]
try:
    extraction.approve(conn, on_text["id"], on_text["data"])
    raise AssertionError("approvata una presa di posizione prima della sua tesi")
except ValueError:
    pass
claim_id = extraction.approve(conn, claim["id"], claim["data"])
stance_ids = [extraction.approve(conn, p["id"], p["data"]) for p in (on_text, on_graph)]
edges = {e["id"]: e for e in graph(conn)["edges"]}
assert edges[stance_ids[0]]["object_assertion_id"] == claim_id
assert [v["label"] for v in edges[stance_ids[0]]["speakers"]] == ["Spanghero"]
assert edges[stance_ids[1]]["object_assertion_id"] == romania
assert stance_ids[1] in [t["id"] for t in edges[romania]["targeted_by"]]
# Scartare la tesi scarta anche le prese di posizione su di essa.
extraction.extract(conn, "carne_cavallo", SMENTITE, "Le Monde, seconda edizione", ask=model_with_stances)
pend = extraction.pending(conn)
assert "già nel grafo" in " ".join(pend[2]["warnings"])                 # la contestazione di Comigel c'è già
extraction.reject(conn, pend[0]["id"])
assert [p["id"] for p in extraction.pending(conn)] == [pend[2]["id"]]
conn.close()
ok("le smentite si estraggono: puntano a una tesi del grafo o dello stesso testo, e si approvano dopo di essa")

# 27. Valori numerici: letti, estratti, confrontati
from core.database import parse_value
assert parse_value("tra il 60 e il 100 %") == (60, 100, "%") and parse_value("0,5 kg") == (0.5, 0.5, "kg")
assert parse_value("1.200 tonnellate") == (1200, 1200, "tonnellate") and parse_value("fino al 20%") == (0, 20, "%")
subprocess.run([sys.executable, "seed_carne_cavallo.py"], check=True, capture_output=True)
conn = connect("carne_cavallo")
values = {(e["subject"], e["relation"]): e["value"] for e in graph(conn)["edges"] if e["value"]}
assert values == {("Hamburger di manzo Tesco", "contiene"): "29 %", ("Lasagne di manzo Findus", "contiene"): "60–100 %"}
VALORI = "Un secondo laboratorio trova nelle lasagne Findus solo il 5% di carne equina, e un livello molto alto altrove."


def model_with_values(system, user, schema):
    assert "valore" in schema["properties"]["affermazioni"]["items"]["properties"]
    base = {"tipo_soggetto": "prodotto", "relazione": "contiene", "tipo_oggetto": "materia prima",
            "tipo_affermazione": "documentato", "data": "", "voce": "", "tipo_voce": ""}
    return {"nuove_relazioni": [], "affermazioni": [
        dict(base, soggetto="Lasagne di manzo Findus", oggetto="Carne equina nelle lasagne", valore="solo il 5%",
             estratto="trova nelle lasagne Findus solo il 5% di carne equina"),
        dict(base, soggetto="Polpette IKEA", oggetto="Carne equina nelle lasagne", valore="molto alto",
             estratto="un livello molto alto altrove")]}


extraction.extract(conn, "carne_cavallo", VALORI, "Laboratorio B", ask=model_with_values)
good, bad = extraction.pending(conn)
assert good["data"]["valore"] == "5 %" and not any("Valore" in w for w in good["warnings"])
assert any("non leggibile" in w for w in bad["warnings"])
try:
    extraction.approve(conn, bad["id"], bad["data"])
    raise AssertionError("approvato un valore illeggibile")
except ValueError:
    pass
extraction.approve(conn, good["id"], good["data"])
weak = {w["titolo"]: w["voci"] for w in graph(conn)["weak"]}
assert any("5 %" in v["testo"] and "60–100 %" in v["testo"] for v in weak["Valori discordanti"])
conn.close()
ok("i valori numerici si leggono anche in italiano («tra il 60 e il 100 %»), si estraggono e i discordanti emergono")

# 28. Fonti aperte: i risultati di ogni servizio diventano voci uniformi, i testi lunghi si troncano
from core import sources
wiki = sources.parse_wikipedia({"query": {"search": [{"title": "Scandalo della carne di cavallo",
                                                      "snippet": "lo <span class=\"m\">scandalo</span>", "timestamp": "2026-10-01T10:00:00Z"}]}}, "it")
assert wiki[0]["url"] == "https://it.wikipedia.org/wiki/Scandalo_della_carne_di_cavallo"
assert wiki[0]["estratto"] == "lo scandalo…" and wiki[0]["data"] == "2026-10-01"
assert (wiki[0]["editore"], wiki[0]["natura"], wiki[0]["lingua"], wiki[0]["canale"]) == \
       ("Wikipedia (it)", "terziaria", "italiano", "Wikipedia")
news = sources.parse_gdelt({"articles": [{"url": "https://x.it/a", "title": "T", "seendate": "20260917T120000Z",
                                          "domain": "x.it", "language": "Italian"}]})
assert news[0]["data"] == "2026-09-17" and news[0]["genere"] == "articolo" and news[0]["natura"] == ""
assert news[0]["editore"] == "x.it" and news[0]["canale"] == "GDELT" and news[0]["lingua"] == "italiano"
web = sources.parse_tavily({"results": [{"title": "T", "url": "https://www.bbc.com/n", "content": "c", "published_date": None}]})
assert web[0]["editore"] == "bbc.com" and web[0]["canale"] == "Tavily" and web[0]["genere"] == ""
paper = sources.parse_openalex({"results": [{"display_name": "Food fraud", "doi": "https://doi.org/10.1/x",
                                             "publication_year": 2019, "abstract_inverted_index": {"fraud": [1], "Food": [0]}}]})
assert paper[0]["testo"] == "Food fraud" and paper[0]["data"] == "2019"
real_http = sources.http
sources.http = lambda url, *a, **k: {"query": {"pages": {"1": {"extract": "Intro.\n\n== Storia ==\nNel 2013."}}}}
assert sources.fetch_wikipedia("https://it.wikipedia.org/wiki/Prova") == "Intro.\n\nStoria\n\nNel 2013."
sources.http = real_http
long_text = ("Paragrafo di prova. " * 40 + "\n\n") * 40
text, full = sources.fetch_text({"url": "https://doi.org/x", "testo": long_text})
assert len(text) <= extraction.limit("caratteri_per_testo") and full == len(long_text) and text.endswith("prova. ")
assert sources.fetch_text({"url": "u", "testo": "breve"}) == ("breve", None)
_, errors = sources.search("x", ["tavily"]) if not sources.keys().get("tavily", {}).get("chiave") else ([], {"Web (Tavily)": "-"})
assert "Web (Tavily)" in errors                            # senza chiave la fonte si segnala, non blocca
ok("le fonti aperte (Wikipedia, GDELT, web, OpenAlex) danno risultati uniformi e i testi lunghi si troncano")

# 29. Il motore conosce documenti, non servizi: editore, canale e natura sono distinti, e l'archivio
#     mostra da dove viene ciò che sa
import base64, io, zipfile
from core.database import SOURCE_NATURES, add_source
docx = io.BytesIO()
with zipfile.ZipFile(docx, "w") as z:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>Primo </w:t></w:r>'
                                    f'<w:r><w:t>paragrafo.</w:t></w:r></w:p><w:p><w:r><w:t>Secondo.</w:t></w:r></w:p></w:body></w:document>')
assert sources.read_file("verbale.docx", docx.getvalue()) == "Primo paragrafo.\n\nSecondo."
assert sources.read_file("nota.txt", "Città più caffè".encode("cp1252")) == "Città più caffè"
f = sources.file_item("Verbale del consiglio.docx", docx.getvalue())
assert (f["titolo"], f["canale"], f["url"], f["natura"]) == ("Verbale del consiglio", "file del PC", "file:Verbale del consiglio.docx", "")
try:
    sources.read_file("foto.jpg", b"x")
    raise AssertionError("letto un formato non supportato")
except sources.SourceError:
    pass

subprocess.run([sys.executable, "seed_carne_cavallo.py"], check=True, capture_output=True)
conn = connect("carne_cavallo")
try:
    add_source(conn, "x", nature="quaternaria")
    raise AssertionError("accettata una natura inventata")
except ValueError:
    pass
# Due articoli dello stesso editore non sono due fonti indipendenti; un terzo editore sì.
TESTO_A = "Secondo Le Monde, Comigel fornisce Findus anche in Svezia."
def model_one(system, user, schema):
    return {"nuove_relazioni": [], "prese_di_posizione": [], "affermazioni": [
        {"soggetto": "Comigel", "tipo_soggetto": "azienda", "relazione": "fornisce", "oggetto": "Spanghero",
         "tipo_oggetto": "azienda", "tipo_affermazione": "documentato", "data": "", "voce": "", "tipo_voce": "",
         "valore": "", "estratto": "Comigel fornisce Findus"}]}
for title, publisher in (("Articolo 1", "Le Monde"), ("Articolo 2", "Le Monde")):
    extraction.extract(conn, "carne_cavallo", TESTO_A, title, "articolo", ask=model_one,
                       meta={"editore": publisher, "canale": "GDELT", "natura": "secondaria", "lingua": "francese"})
for p in extraction.pending(conn):
    extraction.approve(conn, p["id"], p["data"])
g = graph(conn)
single = {w["titolo"]: w["voci"] for w in g["weak"]}["Una sola fonte"]
assert any("Comigel — fornisce → Spanghero" in v["testo"] for v in single)          # stesso editore: una sola fonte
edge = next(e for e in g["edges"] if e["subject"] == "Comigel" and e["object"] == "Spanghero")
assert (edge["source_publisher"], edge["source_channel"], edge["source_nature"]) == ("Le Monde", "GDELT", "secondaria")
assert edge["source_label"] == "Articolo 1"                                          # il canale non entra nel titolo
comp = g["composition"]
assert ("Le Monde", 2) in comp["per"]["editore"] and ("GDELT", 2) in comp["per"]["canale"]
assert ("inserita a mano", comp["fonti"] - 2) in comp["per"]["canale"]
assert any("non è classificata" in a for a in comp["avvisi"])                        # i dati di prova non lo sono
# Lo stesso motore con un testo incollato a mano: nessun canale, la fonte resta completa.
extraction.extract(conn, "carne_cavallo", TESTO_A, "Appunti", ask=model_one, meta={"editore": "Daniele", "natura": "primaria"})
assert tuple(conn.execute("SELECT channel, nature FROM sources WHERE label = 'Appunti'").fetchone()) == (None, "primaria")
conn.close()
ok("il motore distingue editore, canale e natura delle fonti, legge i file del PC e mostra la composizione dell'archivio")

print("\nTutti i controlli superati.")
