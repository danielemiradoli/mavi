"""Estrazione di asserzioni da un testo con un modello linguistico e coda di revisione.

Il modello propone, la persona decide: nulla entra nel grafo senza approvazione.
Ogni proposta viene controllata prima di arrivare in coda:
- relazioni e tipi devono stare nella scheda del clone;
- l'estratto deve comparire parola per parola nel testo, altrimenti è segnalato
  come possibile invenzione del modello;
- i nomi vengono ricondotti alle entità già note (anche per alias o maiuscole);
- un'asserzione già presente nel grafo è segnalata come doppione.
Un'asserzione approvata entra come "da verificare": l'approvazione dice che il
testo afferma quella cosa, non che sia vera.

Prese di posizione: quando nel testo qualcuno contesta (o, secondo la scheda, conferma, smentisce...)
un'affermazione, il modello lo segnala indicando il bersaglio: un'affermazione già nel grafo (codice A + id,
scelta tra quelle che riguardano entità nominate nel testo) oppure una che estrae dallo stesso testo
(codice T + posizione). Nel secondo caso la proposta si approva dopo quella a cui punta.

La scheda può crescere: quando un fatto rilevante non rientra in nessuna relazione,
il modello propone una relazione nuova (nome, definizione, tipi ammessi) con esempi
tratti dal testo. Se la persona la approva, entra in clone.json e gli esempi
diventano proposte normali; se la scarta, spariscono anche gli esempi.

Il modello si sceglie nel file impostazioni.json, nella cartella principale:
- "fornitore" indica quale usare;
- "fornitori" elenca quelli configurati: un modello locale con Ollama, oppure un
  servizio cloud compatibile con le API di OpenAI (Groq, Gemini...), con la sua chiave.
Senza impostazioni.json si usa Gemma 3 4B in locale.
"""

import json
import re
import sqlite3
import urllib.error
import urllib.request

from .database import (CLAIM_TYPES, ROOT, add_assertion, add_assertion_about, add_entity, add_source, add_speaker,
                       format_value, normalize_date, parse_value, read_profile, sync_profile, write_profile)

SETTINGS = ROOT / "impostazioni.json"
DEFAULT_SETTINGS = {
    "fornitore": "ollama",
    "fornitori": {"ollama": {"tipo": "ollama", "indirizzo": "http://localhost:11434", "modello": "gemma3:4b"}},
}
FIELDS = ("soggetto", "tipo_soggetto", "relazione", "oggetto", "tipo_oggetto",
          "tipo_affermazione", "data", "estratto", "voce", "tipo_voce", "valore")


ABOUT_FIELDS = ("soggetto", "tipo_soggetto", "relazione", "bersaglio", "tipo_affermazione", "data", "estratto")
MAX_CLAIMS = 60          # affermazioni del grafo mostrate al modello per ogni blocco di testo


def entity_relations(profile):
    """Le relazioni tra entità."""
    return [r for r in profile["relazioni"] if r.get("oggetto", "entita") == "entita"]


def about_relations(profile):
    """Le relazioni il cui oggetto è un'altra affermazione (es. «contesta»)."""
    return [r for r in profile["relazioni"] if r.get("oggetto") == "affermazione"]


def describe_assertion(conn, aid, depth=0):
    """Un'affermazione in una riga: «Soggetto — relazione → oggetto»."""
    row = conn.execute(
        """SELECT s.label AS subject, a.relation, o.label AS object, a.object_assertion_id
           FROM assertions a JOIN entities s ON s.id = a.subject_id
           LEFT JOIN entities o ON o.id = a.object_id WHERE a.id = ?""", (aid,)).fetchone()
    if not row:
        return f"[affermazione {aid}]"
    obj = row["object"] if row["object"] is not None else (
        f"[{describe_assertion(conn, row['object_assertion_id'], depth + 1)}]" if depth < 2 else "[affermazione]")
    return f"{row['subject']} — {row['relation']} → {obj}"


def claims_for(conn, text, limit=MAX_CLAIMS):
    """Le affermazioni del grafo (non ritirate) che toccano entità nominate nel testo:
    il modello può indicarle come bersaglio di una presa di posizione."""
    t = norm(text)
    names = {}
    for eid, name in conn.execute("SELECT id, label FROM entities UNION SELECT entity_id, alias FROM aliases"):
        if len(name) > 2 and norm(name) in t:
            names[eid] = True
    if not names:
        return []
    marks = ",".join("?" * len(names))
    rows = conn.execute(
        f"""SELECT id FROM assertions WHERE retracted_at IS NULL
            AND (subject_id IN ({marks}) OR object_id IN ({marks})) ORDER BY id DESC LIMIT ?""",
        (*names, *names, limit)).fetchall()
    ids = {r[0] for r in rows}
    # Anche le tesi a cui quelle affermazioni puntano (es. ciò che una smentita già nota contesta).
    ids |= {r[0] for r in conn.execute(
        f"""SELECT object_assertion_id FROM assertions WHERE id IN ({",".join("?" * len(ids))})
            AND object_assertion_id IS NOT NULL""", tuple(ids))} if ids else set()
    return [(aid, describe_assertion(conn, aid)) for aid in sorted(ids)]


def response_schema(profile):
    """Schema JSON imposto al modello: relazioni e tipi possono essere solo quelli della scheda."""
    item = {
        "type": "object",
        "properties": {
            "soggetto": {"type": "string"},
            "tipo_soggetto": {"type": "string", "enum": profile["tipi_entita"]},
            "relazione": {"type": "string", "enum": [r["nome"] for r in entity_relations(profile)]},
            "oggetto": {"type": "string"},
            "tipo_oggetto": {"type": "string", "enum": profile["tipi_entita"]},
            "tipo_affermazione": {"type": "string", "enum": list(CLAIM_TYPES)},
            "data": {"type": "string"},
            "estratto": {"type": "string"},
            "voce": {"type": "string"},
            "tipo_voce": {"type": "string"},
            "valore": {"type": "string"},
        },
        "required": list(FIELDS),
    }
    claim = {"type": "object", "properties": {f: {"type": "string"} for f in FIELDS},
             "required": list(FIELDS)}
    new_relation = {
        "type": "object",
        "properties": {
            "nome": {"type": "string"},
            "definizione": {"type": "string"},
            "da": {"type": "array", "items": {"type": "string"}},
            "a": {"type": "array", "items": {"type": "string"}},
            "esempi": {"type": "array", "items": claim},
        },
        "required": ["nome", "definizione", "da", "a", "esempi"],
    }
    schema = {"type": "object",
              "properties": {"affermazioni": {"type": "array", "items": item},
                             "nuove_relazioni": {"type": "array", "items": new_relation}},
              "required": ["affermazioni", "nuove_relazioni"]}
    if about_relations(profile):
        stance = {"type": "object",
                  "properties": {f: {"type": "string"} for f in ABOUT_FIELDS},
                  "required": list(ABOUT_FIELDS)}
        stance["properties"]["relazione"] = {"type": "string", "enum": [r["nome"] for r in about_relations(profile)]}
        stance["properties"]["tipo_soggetto"] = {"type": "string", "enum": profile["tipi_entita"]}
        stance["properties"]["tipo_affermazione"] = {"type": "string", "enum": list(CLAIM_TYPES)}
        schema["properties"]["prese_di_posizione"] = {"type": "array", "items": stance}
        schema["required"].append("prese_di_posizione")
    return schema


def build_prompt(profile, known, text, claims=()):
    relations = "\n".join(
        f'- "{r["nome"]}" ({" o ".join(r.get("da", ["qualsiasi"]))} → {" o ".join(r.get("a", ["qualsiasi"]))}): '
        f'{r["definizione"]}' for r in entity_relations(profile))
    system = f"""Estrai dal testo le affermazioni pertinenti a questo dominio: {profile["dominio"]}.
Obiettivo dell'archivio: {profile["obiettivo"]}

Ogni affermazione collega un soggetto e un oggetto con UNA di queste relazioni:
{relations}

Tipi di entità ammessi: {", ".join(profile["tipi_entita"])}.

Tipo di affermazione:
- "documentato": un fatto riportato come accertato (un test, un ritiro, una sentenza, una dichiarazione resa);
- "interpretazione": un giudizio o un'accusa di qualcuno;
- "ipotesi": qualcosa presentato come possibile o non provato;
- "inferenza": una deduzione che il testo ricava da altri fatti.

Regole:
- "estratto" è la frase del testo che sostiene l'affermazione, copiata parola per parola.
- "voce" è chi fa l'affermazione dentro il testo: la persona, l'istituzione o l'organizzazione citata
  (es. «come spiega Mario Rossi…», «secondo Europol…»), con il suo tipo in "tipo_voce".
  Lascia entrambi vuoti quando è il testo stesso a riportare il fatto.
- "valore" è la quantità che l'affermazione misura, se il testo la dice (percentuale, peso, prezzo,
  numero di campioni...), con l'unità: es. "29 %", "60-100 %", "750 tonnellate". Altrimenti stringa vuota.
- "data" è quando il fatto avviene, nel formato AAAA, AAAA-MM o AAAA-MM-GG; stringa vuota se il testo non la dice.
- Se un'entità è già nota, usa esattamente il suo nome.
- Rispetta i tipi indicati tra parentesi per ogni relazione: prima il soggetto, poi l'oggetto.
- Soggetto e oggetto sono entità con un nome proprio (persone, aziende, istituzioni, prodotti, paesi...),
  mai concetti generici come «etichettatura» o «carne bovina».
- In "affermazioni" metti solo i fatti che una delle relazioni elencate descrive esattamente.
- Se un fatto importante per l'obiettivo dell'archivio non è descritto da nessuna relazione,
  NON forzarlo: proponi una relazione nuova in "nuove_relazioni", con un nome breve al presente
  (es. «coordina», «indaga su»), una definizione di una frase, i tipi ammessi per soggetto ("da")
  e oggetto ("a") — usa i tipi esistenti se possibile, altrimenti nomi di tipi nuovi al singolare —
  e uno o più "esempi" tratti dal testo, con la stessa forma delle affermazioni.
- Non proporre relazioni che duplicano quelle esistenti, né relazioni per dettagli marginali.
- Non inventare nulla che non sia nel testo. Se non trovi nulla, restituisci elenchi vuoti.
{stance_rules(profile)}
Rispondi solo con un oggetto JSON di questa forma:
{{"affermazioni": [{{"soggetto": "", "tipo_soggetto": "", "relazione": "", "oggetto": "", "tipo_oggetto": "",
"tipo_affermazione": "", "data": "", "estratto": "", "voce": "", "tipo_voce": "", "valore": ""}}],
"nuove_relazioni": [{{"nome": "", "definizione": "", "da": [""], "a": [""], "esempi": [ ... ]}}]{
    ', "prese_di_posizione": [{"soggetto": "", "tipo_soggetto": "", "relazione": "", "bersaglio": "", '
    '"tipo_affermazione": "", "data": "", "estratto": ""}]' if about_relations(profile) else ""}}}"""
    listed = "\n".join(f"A{aid}: {line}" for aid, line in claims) or "nessuna"
    user = f"""Entità già note: {", ".join(known) if known else "nessuna"}.
""" + (f"""
Affermazioni già nell'archivio che riguardano entità del testo:
{listed}
""" if about_relations(profile) else "") + f"""
TESTO:
{text}"""
    return system, user


def stance_rules(profile):
    """Istruzioni per le prese di posizione su affermazioni, se la scheda le prevede."""
    rels = about_relations(profile)
    if not rels:
        return ""
    listed = "\n".join(f'- "{r["nome"]}" ({" o ".join(r.get("da", ["qualsiasi"]))}): {r["definizione"]}' for r in rels)
    return f"""
Prese di posizione: quando nel testo qualcuno si pronuncia su un'affermazione (la contesta, la nega,
la respinge...), mettilo in "prese_di_posizione" con una di queste relazioni:
{listed}
- "soggetto" è chi si pronuncia, con il suo tipo in "tipo_soggetto".
- "bersaglio" è l'affermazione su cui si pronuncia: il codice di un'affermazione già nell'archivio
  (es. "A12", dall'elenco che ricevi) oppure di una che estrai tu da questo testo, indicata con T
  e la sua posizione nell'elenco "affermazioni" contando da 1 (es. "T2").
  Se la tesi contestata non è già nell'archivio, estraila prima come affermazione (con la voce di chi la sostiene).
- Usa solo bersagli che esistono; se non sai quale affermazione è contestata, non proporre nulla.
"""


class ModelError(Exception):
    """Il modello non è raggiungibile o ha risposto con un errore."""


def settings():
    if SETTINGS.exists():
        return json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    return DEFAULT_SETTINGS


def provider(name=None):
    """Il fornitore da usare: quello indicato, oppure quello scelto in impostazioni.json."""
    s = settings()
    name = name or s["fornitore"]
    if name not in s["fornitori"]:
        raise ModelError(f"Il fornitore «{name}» non è configurato in impostazioni.json.")
    return dict(s["fornitori"][name], nome=name)


def describe(prov):
    return f'{prov["modello"]} ({prov["nome"]})'


def parse_json(content):
    """Legge il JSON della risposta, anche se il modello lo ha racchiuso in un blocco di codice."""
    start, end = content.find("{"), content.rfind("}")
    try:
        return json.loads(content[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        raise ValueError("Il modello ha restituito una risposta non leggibile: riprova o usa un testo più breve.")


def post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          # Alcuni servizi (es. Groq, dietro Cloudflare) rifiutano
                                          # l'intestazione predefinita di Python con l'errore 1010.
                                          "User-Agent": "MAVI/0.8 (+https://github.com)",
                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())


def ask_model(system, user, schema, prov=None):
    """Chiede al modello le asserzioni. Restituisce il JSON della risposta."""
    prov = prov or provider()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        if prov["tipo"] == "ollama":
            reply = post(f'{prov["indirizzo"]}/api/chat', {
                "model": prov["modello"], "stream": False, "format": schema,
                "options": {"temperature": 0, "num_ctx": 8192}, "messages": messages})
            return parse_json(reply["message"]["content"])

        if not prov.get("chiave"):
            raise ModelError(f'Manca la chiave di {prov["nome"]} in impostazioni.json.')
        url = f'{prov["indirizzo"].rstrip("/")}/chat/completions'
        headers = {"Authorization": f'Bearer {prov["chiave"]}'}
        body = {"model": prov["modello"], "temperature": 0, "messages": messages,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "affermazioni", "schema": schema}}}
        try:
            reply = post(url, body, headers)
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            # Alcuni modelli non accettano lo schema: si ripiega sul semplice formato JSON.
            body["response_format"] = {"type": "json_object"}
            reply = post(url, body, headers)
        return parse_json(reply["choices"][0]["message"]["content"])
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        hint = {401: "la chiave non è valida", 403: "accesso negato (chiave senza permessi per il modello, o richiesta bloccata dal servizio)",
                404: "il modello non esiste o non è installato",
                429: "superato il limite di richieste: attendi un minuto e riprova"}.get(e.code, "")
        raise ModelError(f"{describe(prov)} ha risposto con l'errore {e.code}"
                         f"{': ' + hint if hint else ''}. {detail}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        where = "Ollama è avviato?" if prov["tipo"] == "ollama" else "La connessione a internet funziona?"
        raise ModelError(f'{describe(prov)} non risponde su {prov["indirizzo"]} ({e}). {where}')


def chunks(text, size=2500):
    """Divide il testo in blocchi di paragrafi interi, per non superare la memoria del modello."""
    parts, current = [], ""
    for para in re.split(r"\n\s*\n", text.strip()):
        if current and len(current) + len(para) > size:
            parts.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        parts.append(current)
    return parts


def norm(s):
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("«", '"').replace("»", '"')
    return re.sub(r"\s+", " ", s).strip()


def match_entity(conn, name):
    """Entità con quel nome o alias, ignorando maiuscole e spazi. Restituisce (id, nome) o None."""
    row = conn.execute(
        """SELECT id, label FROM entities WHERE LOWER(TRIM(label)) = LOWER(TRIM(?))
           UNION SELECT e.id, e.label FROM aliases a JOIN entities e ON e.id = a.entity_id
                 WHERE LOWER(TRIM(a.alias)) = LOWER(TRIM(?))""",
        (name, name),
    ).fetchone()
    return (row[0], row[1]) if row else None


def check(conn, profile, text, raw):
    """Ripulisce una proposta del modello e ne elenca i problemi."""
    p = {f: str(raw.get(f) or "").strip() for f in FIELDS}
    warnings = []
    relations = {r["nome"].lower(): r["nome"] for r in entity_relations(profile)}
    types = {t.lower(): t for t in profile["tipi_entita"]}

    p["relazione"] = relations.get(p["relazione"].lower(), p["relazione"])
    if p["relazione"] not in relations.values():
        warnings.append(f"Relazione «{p['relazione']}» non prevista dalla scheda.")
    rule = next((r for r in entity_relations(profile) if r["nome"] == p["relazione"]), {})
    for side in ("soggetto", "oggetto"):
        found = match_entity(conn, p[side]) if p[side] else None
        if found:
            p[side] = found[1]
            p[f"tipo_{side}"] = conn.execute("SELECT type FROM entities WHERE id = ?", (found[0],)).fetchone()[0]
        if not p[side]:
            warnings.append(f"Manca il {side}.")
        t = f"tipo_{side}"
        p[t] = types.get(p[t].lower(), p[t])
        if not found and p[t] not in types.values():
            warnings.append(f"Tipo «{p[t]}» non previsto dalla scheda.")
        allowed = rule.get("da" if side == "soggetto" else "a")
        if allowed and p[t] not in allowed:
            warnings.append(f"«{p['relazione']}» vuole come {side} {' o '.join(allowed)}, "
                            f"ma «{p[side]}» è {p[t]}.")
    if p["tipo_affermazione"] not in CLAIM_TYPES:
        warnings.append(f"Tipo di affermazione «{p['tipo_affermazione']}» non valido.")
    try:
        p["data"] = normalize_date(p["data"]) or ""
    except ValueError as e:
        warnings.append(str(e))
    try:
        p["valore"] = format_value(*parse_value(p["valore"]))
    except ValueError as e:
        warnings.append(str(e))
    if p["voce"]:
        found = match_entity(conn, p["voce"])
        if found:
            p["voce"] = found[1]
            p["tipo_voce"] = conn.execute("SELECT type FROM entities WHERE id = ?", (found[0],)).fetchone()[0]
        else:
            p["tipo_voce"] = types.get(p["tipo_voce"].lower(), p["tipo_voce"])
            if p["tipo_voce"] not in types.values():
                warnings.append(f"Chi parla («{p['voce']}»): scegli un tipo tra quelli della scheda.")
    else:
        p["tipo_voce"] = ""
    if not p["estratto"]:
        warnings.append("Manca l'estratto: impossibile verificare che il testo lo dica.")
    elif norm(p["estratto"]) not in norm(text):
        warnings.append("L'estratto non compare nel testo: possibile invenzione del modello.")

    s, o = match_entity(conn, p["soggetto"]), match_entity(conn, p["oggetto"])
    if s and o and conn.execute(
        "SELECT 1 FROM assertions WHERE subject_id = ? AND relation = ? AND object_id = ? "
        "AND retracted_at IS NULL",
        (s[0], p["relazione"], o[0]),
    ).fetchone():
        warnings.append("Un'asserzione uguale è già nel grafo.")
    return p, warnings


def check_about(conn, profile, text, raw, claims, chunk_ids):
    """Ripulisce una presa di posizione. Restituisce (proposta, avvisi), oppure None se il bersaglio
    non esiste (non c'è nulla da correggere: la proposta viene lasciata cadere)."""
    p = {f: str(raw.get(f) or "").strip() for f in ABOUT_FIELDS}
    code = p.pop("bersaglio").upper().replace(" ", "")
    p["bersaglio_affermazione"] = p["bersaglio_proposta"] = None
    if re.fullmatch(r"A\d+", code) and int(code[1:]) in dict(claims):
        p["bersaglio_affermazione"] = int(code[1:])
        p["bersaglio"] = dict(claims)[int(code[1:])]
    elif re.fullmatch(r"T\d+", code) and 0 < int(code[1:]) <= len(chunk_ids) and chunk_ids[int(code[1:]) - 1]:
        pid, line = chunk_ids[int(code[1:]) - 1]
        p["bersaglio_proposta"] = pid
        p["bersaglio"] = line
    else:
        return None
    warnings = []
    rels = {r["nome"].lower(): r for r in about_relations(profile)}
    types = {t.lower(): t for t in profile["tipi_entita"]}
    rule = rels.get(p["relazione"].lower())
    if rule:
        p["relazione"] = rule["nome"]
    else:
        warnings.append(f"Relazione «{p['relazione']}» non prevista dalla scheda.")
    found = match_entity(conn, p["soggetto"]) if p["soggetto"] else None
    if found:
        p["soggetto"] = found[1]
        p["tipo_soggetto"] = conn.execute("SELECT type FROM entities WHERE id = ?", (found[0],)).fetchone()[0]
    else:
        p["tipo_soggetto"] = types.get(p["tipo_soggetto"].lower(), p["tipo_soggetto"])
    if not p["soggetto"]:
        warnings.append("Manca chi si pronuncia.")
    elif rule and rule.get("da") and p["tipo_soggetto"] not in rule["da"]:
        warnings.append(f"«{rule['nome']}» vuole come soggetto {' o '.join(rule['da'])}, "
                        f"ma «{p['soggetto']}» è {p['tipo_soggetto']}.")
    if p["tipo_affermazione"] not in CLAIM_TYPES:
        warnings.append(f"Tipo di affermazione «{p['tipo_affermazione']}» non valido.")
    try:
        p["data"] = normalize_date(p["data"]) or ""
    except ValueError as e:
        warnings.append(str(e))
    if not p["estratto"]:
        warnings.append("Manca l'estratto: impossibile verificare che il testo lo dica.")
    elif norm(p["estratto"]) not in norm(text):
        warnings.append("L'estratto non compare nel testo: possibile invenzione del modello.")
    if found and p["bersaglio_affermazione"] and conn.execute(
        "SELECT 1 FROM assertions WHERE subject_id = ? AND relation = ? AND object_assertion_id = ? "
        "AND retracted_at IS NULL", (found[0], p["relazione"], p["bersaglio_affermazione"])).fetchone():
        warnings.append("Questa presa di posizione è già nel grafo.")
    return p, warnings


def extract(conn, clone_name, text, label, kind=None, date=None, url=None,
            speaker=None, speaker_type=None, ask=None):
    """Registra il testo come fonte, chiede al modello le asserzioni e le mette in coda.
    Restituisce il numero di proposte create."""
    profile = read_profile(clone_name)
    source_id = add_source(conn, label, kind or None, normalize_date(date), url or None)
    if speaker:
        found = match_entity(conn, speaker)
        if not found and not speaker_type:
            raise ValueError(f"«{speaker}» non è ancora nel grafo: indica che tipo di entità è.")
        try:
            add_speaker(conn, source_id, found[0] if found else add_entity(conn, speaker, speaker_type))
        except sqlite3.IntegrityError:
            raise ValueError(f"Il tipo «{speaker_type}» non è previsto dalla scheda.")
    doc_id = conn.execute("INSERT INTO documents (source_id, text) VALUES (?, ?)",
                          (source_id, text)).lastrowid
    known = [r[0] for r in conn.execute("SELECT label FROM entities ORDER BY label LIMIT 200")]

    seen, new_relations, count = {}, {}, 0
    existing = {r["nome"].lower(): r["nome"] for r in entity_relations(profile)}

    def queue(raw, schema_id=None):
        nonlocal count
        p, warnings = check(conn, profile, text, raw)
        key = (p["soggetto"].lower(), p["relazione"].lower(), p["oggetto"].lower())
        if key in seen:
            return seen[key]
        if schema_id:
            warnings = [waiting(p["relazione"])] + [w for w in warnings if "non previst" not in w]
        pid = conn.execute("INSERT INTO proposals (document_id, data, warnings, schema_proposal_id) "
                           "VALUES (?, ?, ?, ?)", (doc_id, json.dumps(p, ensure_ascii=False),
                                                   json.dumps(warnings, ensure_ascii=False), schema_id)).lastrowid
        seen[key] = (pid, f"{p['soggetto']} — {p['relazione']} → {p['oggetto']}")
        count += 1
        return seen[key]

    for chunk in chunks(text):
        claims = claims_for(conn, chunk) if about_relations(profile) else []
        result = (ask or ask_model)(*build_prompt(profile, known, chunk, claims), response_schema(profile))
        chunk_ids = [queue(raw) for raw in result.get("affermazioni", [])]
        for raw in result.get("prese_di_posizione", []) or []:
            checked = check_about(conn, profile, chunk, raw, claims, chunk_ids)
            if not checked:
                continue
            p, warnings = checked
            if p["bersaglio_proposta"]:
                warnings.insert(0, "Si approva dopo l'affermazione a cui si riferisce, che è nella coda.")
            key = (p["soggetto"].lower(), p["relazione"].lower(), p["bersaglio"].lower())
            if key in seen:
                continue
            seen[key] = None
            conn.execute("INSERT INTO proposals (document_id, data, warnings) VALUES (?, ?, ?)",
                         (doc_id, json.dumps(p, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False)))
            count += 1
        for nr in result.get("nuove_relazioni", []):
            name = str(nr.get("nome") or "").strip()
            if not name:
                continue
            if name.lower() in existing:          # in realtà esiste già: esempi come proposte normali
                for ex in nr.get("esempi") or []:
                    queue(dict(ex, relazione=existing[name.lower()]))
                continue
            if name.lower() not in new_relations:
                spec = {"nome": name, "definizione": str(nr.get("definizione") or "").strip(),
                        "da": [str(t).strip() for t in nr.get("da") or [] if str(t).strip()],
                        "a": [str(t).strip() for t in nr.get("a") or [] if str(t).strip()]}
                new_relations[name.lower()] = (conn.execute(
                    "INSERT INTO schema_proposals (document_id, data) VALUES (?, ?)",
                    (doc_id, json.dumps(spec, ensure_ascii=False))).lastrowid, name)
            sid, canonical = new_relations[name.lower()]
            for ex in nr.get("esempi") or []:
                queue(dict(ex, relazione=canonical), sid)
    conn.commit()
    return count


def waiting(relation):
    return f"In attesa dell'approvazione della nuova relazione «{relation}» (vedi sopra)."


def pending(conn):
    rows = conn.execute(
        """SELECT p.id, p.data, p.warnings, s.label AS source_label, s.date AS source_date
           FROM proposals p JOIN documents d ON d.id = p.document_id
           JOIN sources s ON s.id = d.source_id
           WHERE p.state = 'in_attesa' ORDER BY p.id"""
    )
    return [{"id": r["id"], "source_label": r["source_label"], "source_date": r["source_date"],
             "data": json.loads(r["data"]), "warnings": json.loads(r["warnings"])} for r in rows]


def approve(conn, proposal_id, fields):
    """Trasforma una proposta (eventualmente corretta) in asserzione. Solleva ValueError se non va."""
    row = conn.execute(
        """SELECT d.source_id FROM proposals p JOIN documents d ON d.id = p.document_id
           WHERE p.id = ? AND p.state = 'in_attesa'""", (proposal_id,)).fetchone()
    if not row:
        raise ValueError("Proposta inesistente o già revisionata.")
    stored = json.loads(conn.execute("SELECT data FROM proposals WHERE id = ?", (proposal_id,)).fetchone()[0])
    if is_about(stored):
        return approve_about(conn, proposal_id, row["source_id"], stored, fields)
    p = {f: str(fields.get(f) or "").strip() for f in FIELDS}
    for f in ("soggetto", "relazione", "oggetto", "tipo_affermazione"):
        if not p[f]:
            raise ValueError(f"Il campo «{f}» è obbligatorio.")
    p["data"] = normalize_date(p["data"]) or ""
    p["valore"] = format_value(*parse_value(p["valore"]))          # ValueError se non è leggibile
    if not conn.execute("SELECT 1 FROM relation_types WHERE name = ?", (p["relazione"],)).fetchone():
        raise ValueError(f"La relazione «{p['relazione']}» non è ancora nella scheda: "
                         "approva prima la nuova relazione, o scegline un'altra.")
    try:
        ids = []
        for side in ("soggetto", "oggetto"):
            found = match_entity(conn, p[side])
            ids.append(found[0] if found else add_entity(conn, p[side], p[f"tipo_{side}"]))
        source_id = voice_source(conn, row["source_id"], p["voce"], p["tipo_voce"])
        aid = add_assertion(conn, ids[0], p["relazione"], ids[1], source_id,
                            claim_type=p["tipo_affermazione"], valid_from=p["data"] or None,
                            excerpt=p["estratto"] or None, value=p["valore"] or None,
                            reason="Approvata dalla coda di revisione")
        conn.execute("UPDATE proposals SET state = 'approvata', assertion_id = ?, data = ? WHERE id = ?",
                     (aid, json.dumps(p, ensure_ascii=False), proposal_id))
        conn.commit()
        return aid
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError("La scheda non ammette questa relazione o questo tipo di entità.")


def is_about(data):
    return bool(data.get("bersaglio_affermazione") or data.get("bersaglio_proposta"))


def approve_about(conn, proposal_id, source_id, stored, fields):
    """Approva una presa di posizione. Il bersaglio non si modifica: se è sbagliato, si scarta."""
    p = {f: str(fields.get(f) or "").strip() for f in ABOUT_FIELDS if f != "bersaglio"}
    for f in ("soggetto", "relazione", "tipo_affermazione"):
        if not p[f]:
            raise ValueError(f"Il campo «{f}» è obbligatorio.")
    p["data"] = normalize_date(p["data"]) or ""
    target = stored.get("bersaglio_affermazione")
    if stored.get("bersaglio_proposta"):
        t = conn.execute("SELECT state, assertion_id FROM proposals WHERE id = ?",
                         (stored["bersaglio_proposta"],)).fetchone()
        if t["state"] == "in_attesa":
            raise ValueError(f"Approva prima l'affermazione a cui si riferisce: «{stored['bersaglio']}».")
        if t["state"] == "scartata":
            raise ValueError("L'affermazione a cui si riferisce è stata scartata: scarta anche questa.")
        target = t["assertion_id"]
    if not conn.execute("SELECT 1 FROM assertions WHERE id = ? AND retracted_at IS NULL", (target,)).fetchone():
        raise ValueError("L'affermazione a cui si riferisce non è più nel grafo: scarta questa proposta.")
    try:
        found = match_entity(conn, p["soggetto"])
        subject = found[0] if found else add_entity(conn, p["soggetto"], p["tipo_soggetto"])
        # Chi si pronuncia è anche chi parla: la fonte è il testo, o una citazione dentro il testo.
        source = voice_source(conn, source_id, p["soggetto"], p["tipo_soggetto"])
        aid = add_assertion_about(conn, subject, p["relazione"], target, source,
                                  claim_type=p["tipo_affermazione"], valid_from=p["data"] or None,
                                  excerpt=p["estratto"] or None, reason="Approvata dalla coda di revisione")
        data = dict(stored, **p)
        conn.execute("UPDATE proposals SET state = 'approvata', assertion_id = ?, data = ? WHERE id = ?",
                     (aid, json.dumps(data, ensure_ascii=False), proposal_id))
        conn.commit()
        return aid
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError("La scheda non ammette questa relazione o questo tipo di entità.")


def voice_source(conn, source_id, voice, voice_type):
    """La fonte da collegare a un'affermazione detta da «voice» dentro il testo.
    Se nel testo parla già quella voce (es. un comunicato), è il testo stesso; altrimenti è una
    citazione: una fonte a sé, riportata nel testo, con quella voce. Una sola citazione per voce e testo."""
    if not voice:
        return source_id
    found = match_entity(conn, voice)
    if not found and not voice_type:
        raise ValueError(f"«{voice}» non è ancora nel grafo: indica che tipo di entità è chi parla.")
    entity_id = found[0] if found else add_entity(conn, voice, voice_type)
    if conn.execute("SELECT 1 FROM source_speakers WHERE source_id = ? AND entity_id = ?",
                    (source_id, entity_id)).fetchone():
        return source_id
    row = conn.execute(
        """SELECT s.id FROM sources s JOIN source_speakers ss ON ss.source_id = s.id
           WHERE s.reported_in = ? AND ss.entity_id = ?""", (source_id, entity_id)).fetchone()
    if row:
        return row[0]
    doc = conn.execute("SELECT label, date, url FROM sources WHERE id = ?", (source_id,)).fetchone()
    voice_label = conn.execute("SELECT label FROM entities WHERE id = ?", (entity_id,)).fetchone()[0]
    cid = add_source(conn, f"{voice_label}, in «{doc['label']}»", "citazione", doc["date"], doc["url"])
    conn.execute("UPDATE sources SET reported_in = ? WHERE id = ?", (source_id, cid))
    add_speaker(conn, cid, entity_id)
    return cid


def add_entity_type(conn, clone_name, name):
    """Aggiunge alla scheda un tipo di entità, senza bisogno di una relazione nuova."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Scrivi il nome del tipo.")
    profile = read_profile(clone_name)
    if name.lower() in {t.lower() for t in profile["tipi_entita"]}:
        raise ValueError(f"Il tipo «{name}» è già nella scheda.")
    profile["tipi_entita"].append(name)
    write_profile(clone_name, profile)
    sync_profile(conn, profile)
    recheck_pending(conn, profile)
    return profile["tipi_entita"]


def recheck_pending(conn, profile):
    """Ricontrolla le proposte in attesa dopo una modifica della scheda
    (non quelle che aspettano ancora l'approvazione di una relazione nuova)."""
    for pid, data, doc in conn.execute(
        """SELECT p.id, p.data, d.text FROM proposals p JOIN documents d ON d.id = p.document_id
           LEFT JOIN schema_proposals sp ON sp.id = p.schema_proposal_id
           WHERE p.state = 'in_attesa' AND (sp.id IS NULL OR sp.state != 'in_attesa')""").fetchall():
        if is_about(json.loads(data)):
            continue
        p, warnings = check(conn, profile, doc, json.loads(data))
        conn.execute("UPDATE proposals SET data = ?, warnings = ? WHERE id = ?",
                     (json.dumps(p, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False), pid))
    conn.commit()


def propose_profile(nome, dominio, obiettivo, domande, ask=None):
    """Chiede al modello una scheda iniziale per un dominio nuovo. Va poi rivista dalla persona."""
    schema = {"type": "object", "properties": {
        "tipi_entita": {"type": "array", "items": {"type": "string"}},
        "relazioni": {"type": "array", "items": {"type": "object", "properties": {
            "nome": {"type": "string"}, "definizione": {"type": "string"}, "inversa": {"type": "string"},
            "da": {"type": "array", "items": {"type": "string"}},
            "a": {"type": "array", "items": {"type": "string"}}},
            "required": ["nome", "definizione", "inversa", "da", "a"]}}},
        "required": ["tipi_entita", "relazioni"]}
    system = """Progetti la scheda iniziale di un archivio di conoscenza: i tipi di entità e le relazioni
con cui verranno registrate le affermazioni tratte dalle fonti (articoli, documenti, testimonianze).

Regole:
- 5-8 tipi di entità, nomi italiani al singolare e in minuscolo (es. «persona», «azienda», «opera»).
- 8-15 relazioni, nomi brevi al presente (es. «fornisce», «è opera di», «indaga su»), ognuna con una
  definizione di una frase, la relazione inversa e i tipi ammessi come soggetto ("da") e oggetto ("a"),
  scelti solo tra i tipi elencati.
- Scegli le relazioni che servono a rispondere alle domande guida; niente relazioni generiche come
  «è collegato a». Non includere «contesta»: c'è già in ogni scheda.
Rispondi solo con un oggetto JSON con le chiavi "tipi_entita" e "relazioni"."""
    user = (f"Nome: {nome}\nDominio: {dominio}\nObiettivo: {obiettivo}\nDomande guida:\n"
            + "\n".join(f"- {d}" for d in domande))
    result = (ask or ask_model)(system, user, schema)
    return {"nome": nome, "dominio": dominio, "obiettivo": obiettivo, "domande": domande,
            "tipi_entita": result.get("tipi_entita", []), "relazioni": result.get("relazioni", [])}


def reject(conn, proposal_id):
    conn.execute("UPDATE proposals SET state = 'scartata' WHERE id = ? AND state = 'in_attesa'",
                 (proposal_id,))
    # Le prese di posizione su questa proposta non hanno più un bersaglio.
    conn.execute("""UPDATE proposals SET state = 'scartata' WHERE state = 'in_attesa'
                    AND json_extract(data, '$.bersaglio_proposta') = ?""", (proposal_id,))
    conn.commit()


def schema_pending(conn):
    """Le relazioni nuove proposte dal modello, con i loro esempi."""
    out = []
    for r in conn.execute(
        """SELECT sp.id, sp.data, s.label AS source_label FROM schema_proposals sp
           JOIN documents d ON d.id = sp.document_id JOIN sources s ON s.id = d.source_id
           WHERE sp.state = 'in_attesa' ORDER BY sp.id"""
    ):
        examples = [json.loads(e[0]) for e in conn.execute(
            "SELECT data FROM proposals WHERE schema_proposal_id = ? AND state = 'in_attesa'", (r["id"],))]
        out.append({"id": r["id"], "source_label": r["source_label"], "data": json.loads(r["data"]),
                    "esempi": [{k: e[k] for k in ("soggetto", "oggetto", "estratto")} for e in examples]})
    return out


def as_list(value):
    if isinstance(value, str):
        value = value.split(",")
    return [str(v).strip() for v in value or [] if str(v).strip()]


def approve_relation(conn, clone_name, schema_id, fields):
    """Aggiunge alla scheda la relazione proposta (eventualmente corretta) e i tipi nuovi che usa."""
    row = conn.execute("SELECT data FROM schema_proposals WHERE id = ? AND state = 'in_attesa'",
                       (schema_id,)).fetchone()
    if not row:
        raise ValueError("Proposta inesistente o già revisionata.")
    proposed = json.loads(row["data"])["nome"]
    name, definition = str(fields.get("nome") or "").strip(), str(fields.get("definizione") or "").strip()
    da, a = as_list(fields.get("da")), as_list(fields.get("a"))
    if not name or not definition or not da or not a:
        raise ValueError("Servono nome, definizione e almeno un tipo per soggetto e oggetto.")
    profile = read_profile(clone_name)
    if name.lower() in {r["nome"].lower() for r in profile["relazioni"]}:
        raise ValueError(f"La relazione «{name}» esiste già nella scheda.")
    new_types = [t for t in dict.fromkeys(da + a) if t not in profile["tipi_entita"]]
    profile["tipi_entita"] += new_types
    profile["relazioni"].append({"nome": name, "definizione": definition, "da": da, "a": a})
    write_profile(clone_name, profile)
    sync_profile(conn, profile)

    # Gli esempi diventano proposte normali, ricontrollate con la scheda aggiornata
    for pid, data, doc in conn.execute(
        """SELECT p.id, p.data, d.text FROM proposals p JOIN documents d ON d.id = p.document_id
           WHERE p.schema_proposal_id = ? AND p.state = 'in_attesa'""", (schema_id,)).fetchall():
        ex = dict(json.loads(data), relazione=name)
        # Se nella correzione i tipi sono cambiati, l'esempio li segue
        for side, allowed in (("soggetto", da), ("oggetto", a)):
            if ex.get(f"tipo_{side}") not in allowed and not match_entity(conn, ex.get(side, "")):
                ex[f"tipo_{side}"] = allowed[0]
        p, warnings = check(conn, profile, doc, ex)
        conn.execute("UPDATE proposals SET data = ?, warnings = ? WHERE id = ?",
                     (json.dumps(p, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False), pid))
    conn.execute("UPDATE schema_proposals SET state = 'approvata', data = ? WHERE id = ?",
                 (json.dumps({"nome": name, "definizione": definition, "da": da, "a": a,
                              "proposta_come": proposed}, ensure_ascii=False), schema_id))
    conn.commit()
    return {"nome": name, "tipi_nuovi": new_types}


def reject_relation(conn, schema_id):
    """Scarta la relazione proposta e, con lei, i suoi esempi."""
    conn.execute("UPDATE schema_proposals SET state = 'scartata' WHERE id = ? AND state = 'in_attesa'",
                 (schema_id,))
    conn.execute("UPDATE proposals SET state = 'scartata' WHERE schema_proposal_id = ? AND state = 'in_attesa'",
                 (schema_id,))
    conn.commit()
