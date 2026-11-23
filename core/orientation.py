"""Orientamento: il quadro di ciò che l'archivio contiene, per ragionarci sopra.

MAVI non dà risposte: mette in fila ciò che risulta da più fonti, ciò che è conteso, chi sono gli attori,
che cosa manca e da dove viene ciò che si sa, e ne ricava domande. Tutto è calcolato con regole esplicite
sul grafo (nessun modello linguistico), uguali per ogni clone e per ogni tipo di fonte; ogni voce porta
all'affermazione o all'entità da cui nasce, per poterla verificare.
"""
from collections import Counter

from .database import graph, read_profile


def line(e):
    when = f' [{e["valid_from"]}]' if e["valid_from"] else ""
    value = f' ({e["value"]})' if e["value"] else ""
    return f'{e["subject"]} — {e["relation"]} → {e["object"]}{value}{when}'


def roots_by_triple(facts):
    groups = {}
    for e in facts:
        groups.setdefault((e["subject_id"], e["relation"], e["object_id"]), []).append(e)
    return {k: {e["source_root"] for e in g} for k, g in groups.items()}


def orientation(conn, clone):
    g = graph(conn)
    profile = read_profile(clone)
    edges, nodes = g["edges"], g["nodes"]
    by_id = {e["id"]: e for e in edges}
    facts = [e for e in edges if not e["object_assertion_id"]]
    roots = roots_by_triple(facts)

    def disputed(e):
        return e["status"] == "smentita" or e["conflicts"] or any(
            by_id[t["id"]]["status"] != "smentita" for t in e["targeted_by"])

    # Ciò che risulta: segnato come certo, oppure sostenuto da almeno due fonti indipendenti e non conteso.
    # Non è «vero»: è ciò su cui l'archivio converge.
    established, seen = [], set()
    for e in facts:
        key = (e["subject_id"], e["relation"], e["object_id"])
        n = len(roots[key])
        if key in seen or disputed(e) or not (e["status"] == "certa" or n >= 2):
            continue
        seen.add(key)
        why = "segnata come certa" if e["status"] == "certa" else f"{n} fonti indipendenti"
        if e["status"] == "certa" and n >= 2:
            why += f", {n} fonti indipendenti"
        established.append({"id": e["id"], "testo": line(e), "perche": why})

    # Ciò che è conteso: chi contesta cosa, versioni incompatibili, smentite, numeri che non tornano.
    contested = []
    for e in edges:
        live = [by_id[t["id"]] for t in e["targeted_by"] if by_id[t["id"]]["status"] != "smentita"]
        if live:
            who = ", ".join(sorted({f'{t["subject"]} ({t["relation"]})' for t in live}))
            contested.append({"id": e["id"], "testo": line(e), "perche": f"{who}; sostenuta da: "
                              + (", ".join(s["label"] for s in e["speakers"]) or e["source_root"]),
                              "stato": e["status"]})
        elif e["status"] == "smentita":
            contested.append({"id": e["id"], "testo": line(e), "perche": "smentita", "stato": e["status"]})
    weak = {w["titolo"]: w["voci"] for w in g["weak"]}
    for item in weak.get("Conflitti aperti", []) + weak.get("Valori discordanti", []):
        contested.append({"id": item["id"], "testo": item["testo"], "perche": "versioni incompatibili", "stato": ""})

    # Attori: le entità più collegate, con quante affermazioni le riguardano, quante ne sostengono come voce
    # e quante ne contestano.
    involved, voiced, contesting = Counter(), Counter(), Counter()
    for e in edges:
        involved[e["subject_id"]] += 1
        if e["object_id"]:
            involved[e["object_id"]] += 1
        if e["object_assertion_id"]:
            contesting[e["subject_id"]] += 1
        for s in e["speakers"]:
            voiced[s["id"]] += 1
    names = {n["id"]: n for n in nodes}
    actors = [{"id": nid, "nome": names[nid]["label"], "tipo": names[nid]["type"], "affermazioni": n,
               "come_voce": voiced[nid], "contesta": contesting[nid]}
              for nid, n in involved.most_common(12) if nid in names]

    # Lacune: ciò che l'archivio non copre ancora.
    used_types = {n["type"] for n in nodes if n["id"] in involved}
    used_relations = {e["relation"] for e in edges}
    gaps = []
    for t in profile["tipi_entita"]:
        if t not in used_types:
            gaps.append({"testo": f"Nessuna entità di tipo «{t}» nel grafo.", "tipo": "scheda"})
    unused = [r["nome"] for r in profile["relazioni"] if r["nome"] not in used_relations]
    if unused:
        gaps.append({"testo": "Relazioni della scheda mai usate: " + ", ".join(f"«{r}»" for r in unused) + ".",
                     "tipo": "scheda"})
    for item in weak.get("Una sola fonte", []):
        gaps.append({"id": item["id"], "testo": item["testo"], "tipo": "una sola fonte"})
    for item in weak.get("Interpretazioni senza voce", []):
        gaps.append({"id": item["id"], "testo": item["testo"], "tipo": "senza voce"})
    lonely = [names[nid] for nid, n in involved.items() if n == 1 and nid in names]
    for n in lonely[:10]:
        gaps.append({"nodo": n["id"], "testo": f"{n['label']} compare in una sola affermazione.", "tipo": "isolata"})
    for a in g["composition"]["avvisi"]:
        gaps.append({"testo": a, "tipo": "provenienza"})

    # Domande: ricavate dalle sezioni precedenti con regole fisse; sono spunti, non risposte.
    questions = []
    for c in contested[:6]:
        if c["perche"] == "versioni incompatibili":
            questions.append({"id": c["id"], "testo": f"Quale delle versioni è sostenuta da prove più dirette? {c['testo']}"})
        elif c["stato"] == "smentita":
            questions.append({"id": c["id"], "testo": f"Chi l'aveva sostenuta e perché? Che cosa ha portato alla smentita? {c['testo']}"})
        else:
            questions.append({"id": c["id"], "testo": f"Su quali prove si basano le due parti? {c['testo']}"})
    for gap in [x for x in gaps if x["tipo"] == "una sola fonte"][:4]:
        questions.append({"id": gap["id"], "testo": f"Esiste una seconda fonte, indipendente da questa, che lo confermi o lo smentisca? {gap['testo']}"})
    for a in actors[:3]:
        if not a["come_voce"]:
            questions.append({"nodo": a["id"], "testo": f"{a['nome']} è al centro di {a['affermazioni']} affermazioni ma non parla mai in prima persona: che cosa ne dice?"})
    if any(x["tipo"] == "provenienza" for x in gaps):
        questions.append({"testo": "Chi non è ancora rappresentato tra le fonti (altre lingue, altri paesi, fonti primarie, le parti in causa)?"})
    for t in [x for x in gaps if x["tipo"] == "scheda" and x["testo"].startswith("Nessuna")][:2]:
        questions.append({"testo": f"{t['testo'][:-1]}: è un'assenza reale o una ricerca che manca?"})

    dates = sorted(d for e in facts for d in (e["valid_from"], e["valid_to"], e["known_from"]) if d)
    return {
        "nome": profile["nome"], "obiettivo": profile.get("obiettivo", ""), "domande_guida": profile.get("domande", []),
        "numeri": {"affermazioni": len(edges), "entita": len(involved), "fonti": g["composition"]["fonti"],
                   "periodo": [dates[0], dates[-1]] if dates else None},
        "assodato": established, "conteso": contested, "attori": actors, "lacune": gaps,
        "domande": questions, "provenienza": g["composition"],
    }
