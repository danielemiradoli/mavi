"""MAVI — server locale. Avvio: python -m uvicorn app:app

Il clone si sceglie dal browser; la scelta resta in clones/.attivo.
La variabile MAVI_CLONE, se presente, decide il clone all'avvio.
"""

import os

from fastapi import Body, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from core import extraction, sources
from core.database import (ROOT, SOURCE_GENRES, SOURCE_NATURES, change_status, connect, create_clone, graph, list_clones,
                           merge_entities, read_profile, retract, validate_profile)

ACTIVE = ROOT / "clones" / ".attivo"


def initial_clone():
    names = [c["nome"] for c in list_clones()]
    for candidate in (os.environ.get("MAVI_CLONE"),
                      ACTIVE.read_text(encoding="utf-8").strip() if ACTIVE.exists() else None):
        if candidate in names:
            return candidate
    return names[0] if names else None


CLONE = initial_clone()

app = FastAPI(title="MAVI")


@app.get("/api/graph")
def api_graph():
    conn = connect(CLONE)
    try:
        return {"clone": CLONE, "profile": read_profile(CLONE), **graph(conn)}
    finally:
        conn.close()


@app.get("/api/clones")
def api_clones():
    return {"attivo": CLONE, "cloni": list_clones()}


@app.post("/api/clone")
def api_switch(payload: dict = Body(...)):
    global CLONE
    name = payload.get("nome")
    if name not in [c["nome"] for c in list_clones()]:
        raise HTTPException(400, f"Il clone «{name}» non esiste.")
    CLONE = name
    ACTIVE.write_text(name, encoding="utf-8")
    return {"attivo": CLONE}


@app.post("/api/clones/propose")
def api_propose_profile(payload: dict = Body(...)):
    nome = (payload.get("nome") or "").strip()
    if not nome or not (payload.get("obiettivo") or "").strip():
        raise HTTPException(400, "Servono almeno il nome e l'obiettivo del nuovo clone.")
    domande = [d.strip() for d in (payload.get("domande") or "").splitlines() if d.strip()]
    try:
        return extraction.propose_profile(nome, payload.get("dominio", ""), payload["obiettivo"], domande)
    except extraction.ModelError as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/clones")
def api_create_clone(payload: dict = Body(...)):
    global CLONE
    try:
        slug = create_clone(payload.get("cartella") or payload.get("scheda", {}).get("nome"),
                            payload.get("scheda") or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    CLONE = slug
    ACTIVE.write_text(slug, encoding="utf-8")
    return {"attivo": slug}


@app.post("/api/clones/validate")
def api_validate_profile(payload: dict = Body(...)):
    try:
        return validate_profile(payload)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/assertions/{aid}/status")
def api_status(aid: int, payload: dict = Body(...)):
    conn = connect(CLONE)
    try:
        change_status(conn, aid, payload.get("stato"), payload.get("data"), payload.get("motivo"))
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.post("/api/assertions/{aid}/retract")
def api_retract(aid: int, payload: dict = Body(...)):
    conn = connect(CLONE)
    try:
        retract(conn, aid, payload.get("motivo"))
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.post("/api/entities/{eid}/merge")
def api_merge(eid: int, payload: dict = Body(...)):
    conn = connect(CLONE)
    try:
        target = extraction.match_entity(conn, payload.get("in") or "")
        if not target:
            raise ValueError("Scegli un'entità già presente nel grafo.")
        merge_entities(conn, eid, target[0])
        return {"in": target[0]}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.post("/api/profile/types")
def api_add_type(payload: dict = Body(...)):
    conn = connect(CLONE)
    try:
        return {"tipi": extraction.add_entity_type(conn, CLONE, payload.get("nome"))}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.post("/api/extract")
def api_extract(payload: dict = Body(...)):
    text, label = (payload.get("testo") or "").strip(), (payload.get("titolo") or "").strip()
    if not text or not label:
        raise HTTPException(400, "Servono il testo e il titolo della fonte.")
    conn = connect(CLONE)
    try:
        n = extraction.extract(conn, CLONE, text, label, payload.get("tipo"), payload.get("data"),
                               payload.get("url"), payload.get("voce"), payload.get("tipo_voce"),
                               meta={k: payload.get(k) for k in ("editore", "natura", "lingua")})
        return {"proposte": n}
    except ValueError as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    except extraction.ModelError as e:
        conn.rollback()
        raise HTTPException(502, str(e))
    finally:
        conn.close()


@app.get("/api/sources")
def api_sources():
    conn = connect(CLONE)
    try:
        profile = read_profile(CLONE)
        known = [r[0] for r in conn.execute("SELECT url FROM sources WHERE url IS NOT NULL")]
        return {"fonti": sources.available(), "nome": profile["nome"],
                "domande": profile.get("domande", []), "gia_lette": known,
                "generi": SOURCE_GENRES, "nature": SOURCE_NATURES}
    finally:
        conn.close()


@app.post("/api/sources/search")
def api_sources_search(payload: dict = Body(...)):
    query = (payload.get("domanda") or "").strip()
    if not query:
        raise HTTPException(400, "Scrivi che cosa cercare.")
    results, errors = sources.search(query, payload.get("fonti") or ["wikipedia"])
    return {"risultati": results, "errori": errors}


@app.post("/api/sources/add")
def api_sources_add(item: dict = Body(...)):
    """Legge il testo completo di un risultato e lo manda all'estrazione: le proposte vanno in coda."""
    if not item.get("url") or not item.get("titolo"):
        raise HTTPException(400, "Risultato incompleto.")
    try:
        text, full = sources.fetch_text(item)
    except sources.SourceError as e:
        raise HTTPException(502, f"«{item['titolo']}»: {e}")
    conn = connect(CLONE)
    try:
        # Il titolo identifica il documento; editore e canale restano campi distinti.
        n = extraction.extract(conn, CLONE, text, item["titolo"], item.get("genere") or None,
                               item.get("data") or None, item["url"],
                               meta={k: item.get(k) for k in ("editore", "canale", "natura", "lingua")})
        return {"proposte": n, "troncato_da": full, "caratteri": len(text)}
    except ValueError as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    except extraction.ModelError as e:
        conn.rollback()
        raise HTTPException(502, str(e))
    finally:
        conn.close()


@app.post("/api/sources/file")
def api_sources_file(payload: dict = Body(...)):
    """Un file del PC (PDF, Word, HTML, testo), inviato dalla pagina in base64: diventa un risultato
    come quelli dei servizi di ricerca, da classificare e mandare alla coda."""
    import base64
    name = (payload.get("nome") or "").strip()
    try:
        data = base64.b64decode(payload.get("contenuto") or "")
        return sources.file_item(name, data)
    except sources.SourceError as e:
        raise HTTPException(400, f"«{name}»: {e}")
    except ValueError:
        raise HTTPException(400, f"«{name}»: file non leggibile.")


@app.get("/api/proposals")
def api_proposals():
    conn = connect(CLONE)
    try:
        return extraction.pending(conn)
    finally:
        conn.close()


@app.post("/api/proposals/{pid}/approve")
def api_approve(pid: int, payload: dict = Body(...)):
    conn = connect(CLONE)
    try:
        return {"asserzione": extraction.approve(conn, pid, payload)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.get("/api/schema_proposals")
def api_schema_proposals():
    conn = connect(CLONE)
    try:
        return extraction.schema_pending(conn)
    finally:
        conn.close()


@app.post("/api/schema_proposals/{sid}/approve")
def api_schema_approve(sid: int, payload: dict = Body(...)):
    conn = connect(CLONE)
    try:
        return extraction.approve_relation(conn, CLONE, sid, payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.post("/api/schema_proposals/{sid}/reject")
def api_schema_reject(sid: int):
    conn = connect(CLONE)
    try:
        extraction.reject_relation(conn, sid)
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/proposals/{pid}/reject")
def api_reject(pid: int):
    conn = connect(CLONE)
    try:
        extraction.reject(conn, pid)
        return {"ok": True}
    finally:
        conn.close()


app.mount("/", StaticFiles(directory=ROOT / "gui", html=True))
