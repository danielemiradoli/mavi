"""Database di un clone MAVI: un solo file SQLite, modello ad asserzioni.

Ogni asserzione è una tripla (soggetto, relazione, oggetto) che porta sempre
con sé la propria fonte.

Ogni clone ha una scheda (clones/<nome>/clone.json) che dichiara i tipi di
entità e le relazioni ammesse. Il database rifiuta tutto ciò che la scheda
non prevede: per un nuovo dominio si scrive una nuova scheda, non nuovo codice.

Tre date distinte, tutte testo ISO anche parziale ("1984", "1984-07", "1984-07-24"):
- valid_from / valid_to: quando il fatto vale nel mondo;
- known_from: da quando l'affermazione circola (se manca, vale la data della fonte);
- date della fonte: quando il documento è stato prodotto.
Una data parziale vale come inizio del periodo ("1984-07" = dal 1° luglio).

Due assi distinti per ogni asserzione:
- claim_type: che genere di affermazione è (documentato, interpretazione, ipotesi, inferenza);
- status: quanto la riteniamo vera ora (certa, da_verificare, smentita).
Ogni cambio di stato è registrato in status_log con data e motivo.

L'oggetto di un'asserzione è un'entità oppure un'altra asserzione
("Il governo rumeno — contesta → [la carne proviene dalla Romania]").
Ogni relazione dichiara nella scheda quale dei due tipi di oggetto accetta.

Ogni relazione può dichiarare nella scheda quali tipi di entità ammette come
soggetto ("da") e come oggetto ("a"): "fornisce" va da azienda ad azienda.

Ogni fonte può indicare chi parla (una o più entità): così il grafo sa
chi sostiene ciascuna affermazione, non solo chi la contesta.
"""

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CLAIM_TYPES = ("documentato", "interpretazione", "ipotesi", "inferenza")
STATUSES = ("certa", "da_verificare", "smentita")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS entity_types (
    name  TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS relation_types (
    name        TEXT PRIMARY KEY,
    definition  TEXT NOT NULL,
    inverse     TEXT,
    target      TEXT NOT NULL DEFAULT 'entita' CHECK (target IN ('entita', 'affermazione'))
);

-- Il quaderno della persona: ipotesi, domande e note sul clone. Non sono affermazioni del grafo:
-- sono il suo ragionamento, che resta distinto da ciò che dicono le fonti.
CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('ipotesi', 'domanda', 'nota')),
    text        TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'aperta' CHECK (state IN ('aperta', 'confermata', 'scartata')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS sources (
    id     INTEGER PRIMARY KEY,
    label  TEXT NOT NULL,
    kind   TEXT,
    date   TEXT,
    url    TEXT
);

CREATE TABLE IF NOT EXISTS source_speakers (
    source_id  INTEGER NOT NULL REFERENCES sources(id),
    entity_id  INTEGER NOT NULL REFERENCES entities(id),
    PRIMARY KEY (source_id, entity_id)
);

CREATE TABLE IF NOT EXISTS entities (
    id     INTEGER PRIMARY KEY,
    label  TEXT NOT NULL UNIQUE,
    type   TEXT NOT NULL REFERENCES entity_types(name)
);

CREATE TABLE IF NOT EXISTS aliases (
    entity_id  INTEGER NOT NULL REFERENCES entities(id),
    alias      TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS assertions (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL REFERENCES entities(id),
    relation    TEXT NOT NULL REFERENCES relation_types(name),
    object_id   INTEGER REFERENCES entities(id),
    object_assertion_id INTEGER REFERENCES assertions(id),
    valid_from  TEXT,
    valid_to    TEXT,
    known_from  TEXT,
    source_id   INTEGER NOT NULL REFERENCES sources(id),
    excerpt     TEXT,
    claim_type  TEXT NOT NULL CHECK (claim_type IN {CLAIM_TYPES}),
    status      TEXT NOT NULL CHECK (status IN {STATUSES}),
    is_manual   INTEGER NOT NULL DEFAULT 0,
    CHECK ((object_id IS NULL) <> (object_assertion_id IS NULL))
);

CREATE TRIGGER IF NOT EXISTS relation_target_check BEFORE INSERT ON assertions
WHEN (NEW.object_assertion_id IS NOT NULL)
     <> ((SELECT target FROM relation_types WHERE name = NEW.relation) = 'affermazione')
BEGIN
    SELECT RAISE(ABORT, 'la relazione non ammette questo tipo di oggetto');
END;

CREATE TABLE IF NOT EXISTS relation_sides (
    relation     TEXT NOT NULL REFERENCES relation_types(name),
    side         TEXT NOT NULL CHECK (side IN ('da', 'a')),
    entity_type  TEXT NOT NULL REFERENCES entity_types(name),
    PRIMARY KEY (relation, side, entity_type)
);

CREATE TRIGGER IF NOT EXISTS relation_sides_check BEFORE INSERT ON assertions
WHEN (EXISTS (SELECT 1 FROM relation_sides WHERE relation = NEW.relation AND side = 'da')
      AND NOT EXISTS (SELECT 1 FROM relation_sides rs JOIN entities e ON e.type = rs.entity_type
                      WHERE rs.relation = NEW.relation AND rs.side = 'da' AND e.id = NEW.subject_id))
  OR (NEW.object_id IS NOT NULL
      AND EXISTS (SELECT 1 FROM relation_sides WHERE relation = NEW.relation AND side = 'a')
      AND NOT EXISTS (SELECT 1 FROM relation_sides rs JOIN entities e ON e.type = rs.entity_type
                      WHERE rs.relation = NEW.relation AND rs.side = 'a' AND e.id = NEW.object_id))
BEGIN
    SELECT RAISE(ABORT, 'la relazione non ammette questi tipi di soggetto o di oggetto');
END;

CREATE TABLE IF NOT EXISTS status_log (
    id            INTEGER PRIMARY KEY,
    assertion_id  INTEGER NOT NULL REFERENCES assertions(id),
    status        TEXT NOT NULL CHECK (status IN {STATUSES}),
    date          TEXT,
    reason        TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id         INTEGER PRIMARY KEY,
    source_id  INTEGER NOT NULL REFERENCES sources(id),
    text       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id            INTEGER PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents(id),
    data          TEXT NOT NULL,
    warnings      TEXT NOT NULL DEFAULT '[]',
    state         TEXT NOT NULL DEFAULT 'in_attesa'
                  CHECK (state IN ('in_attesa', 'approvata', 'scartata')),
    assertion_id  INTEGER REFERENCES assertions(id)
);

CREATE TABLE IF NOT EXISTS schema_proposals (
    id           INTEGER PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES documents(id),
    data         TEXT NOT NULL,
    state        TEXT NOT NULL DEFAULT 'in_attesa'
                 CHECK (state IN ('in_attesa', 'approvata', 'scartata'))
);

CREATE TABLE IF NOT EXISTS entity_merges (
    id            INTEGER PRIMARY KEY,
    merged_label  TEXT NOT NULL,
    merged_type   TEXT NOT NULL,
    into_id       INTEGER NOT NULL REFERENCES entities(id),
    date          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conflicts (
    id           INTEGER PRIMARY KEY,
    assertion_a  INTEGER NOT NULL REFERENCES assertions(id),
    assertion_b  INTEGER NOT NULL REFERENCES assertions(id),
    note         TEXT
);
"""


def clone_dir(clone_name):
    return ROOT / "clones" / clone_name


def db_path(clone_name):
    return clone_dir(clone_name) / "vault" / "context.db"


def read_profile(clone_name):
    """Legge la scheda del dominio (clone.json)."""
    return json.loads((clone_dir(clone_name) / "clone.json").read_text(encoding="utf-8-sig"))


CORE_RELATIONS = [
    {"nome": "contesta", "definizione": "Il soggetto respinge pubblicamente l'affermazione indicata.",
     "inversa": "contestata da", "oggetto": "affermazione"},
]


def list_clones():
    """I cloni presenti, con titolo e dominio presi dalla scheda."""
    out = []
    for d in sorted((ROOT / "clones").glob("*/clone.json")):
        if d.parent.name.startswith("_"):
            continue
        prof = json.loads(d.read_text(encoding="utf-8-sig"))
        out.append({"nome": d.parent.name, "titolo": prof.get("nome", d.parent.name),
                    "dominio": prof.get("dominio", "")})
    return out


def slugify(text):
    import unicodedata
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40]


def validate_profile(profile):
    """Controlla e ripulisce una scheda scritta o proposta. Solleva ValueError con un elenco dei problemi."""
    problems = []
    clean = {k: str(profile.get(k) or "").strip() for k in ("nome", "dominio", "obiettivo")}
    clean["domande"] = [str(d).strip() for d in profile.get("domande") or [] if str(d).strip()]
    types = []
    for t in profile.get("tipi_entita") or []:
        t = str(t).strip()
        if t and t.lower() not in {x.lower() for x in types}:
            types.append(t)
    clean["tipi_entita"] = types
    if not clean["nome"]:
        problems.append("manca il nome")
    if not types:
        problems.append("serve almeno un tipo di entità")
    relations, names = [], set()
    for r in profile.get("relazioni") or []:
        name = str(r.get("nome") or "").strip()
        if not name:
            continue
        if name.lower() in names:
            problems.append(f"la relazione «{name}» compare due volte")
            continue
        names.add(name.lower())
        rel = {"nome": name, "definizione": str(r.get("definizione") or "").strip()}
        if r.get("inversa"):
            rel["inversa"] = str(r["inversa"]).strip()
        if not rel["definizione"]:
            problems.append(f"«{name}»: manca la definizione")
        if r.get("oggetto") == "affermazione":
            rel["oggetto"] = "affermazione"
        for side in ("da", "a"):
            vals = r.get(side) or []
            if isinstance(vals, str):
                vals = vals.split(",")
            vals = [str(v).strip() for v in vals if str(v).strip()]
            unknown = [v for v in vals if v not in types]
            if unknown:
                problems.append(f"«{name}»: tipi non nella scheda: {', '.join(unknown)}")
            if vals and not (side == "a" and rel.get("oggetto") == "affermazione"):
                rel[side] = vals
        relations.append(rel)
    for core in CORE_RELATIONS:                 # relazioni comuni a ogni clone
        if core["nome"] not in names:
            relations.append(dict(core))
    clean["relazioni"] = relations
    if len(relations) <= len(CORE_RELATIONS):
        problems.append("serve almeno una relazione tra entità")
    if problems:
        raise ValueError("Scheda da correggere: " + "; ".join(problems) + ".")
    return clean


def create_clone(slug, profile):
    """Crea un clone nuovo a partire da una scheda valida."""
    slug = slugify(slug)
    if not slug:
        raise ValueError("Scegli un nome per la cartella del clone.")
    if clone_dir(slug).exists():
        raise ValueError(f"Esiste già un clone «{slug}».")
    profile = validate_profile(profile)
    clone_dir(slug).mkdir(parents=True)
    write_profile(slug, profile)
    connect(slug).close()
    return slug


def write_profile(clone_name, profile):
    """Riscrive la scheda, una relazione per riga perché resti leggibile a mano."""
    head = json.dumps({k: v for k, v in profile.items() if k != "relazioni"},
                      ensure_ascii=False, indent=2)[:-2]
    rels = ",\n".join("    " + json.dumps(r, ensure_ascii=False) for r in profile["relazioni"])
    (clone_dir(clone_name) / "clone.json").write_text(
        f'{head},\n  "relazioni": [\n{rels}\n  ]\n}}\n', encoding="utf-8")


def normalize_date(text):
    """Porta una data nella forma ISO usata da MAVI (AAAA, AAAA-MM, AAAA-MM-GG).
    Accetta anche 20260917, 2026/09/17, 17/09/2026, 17.09.2026, 17-09-2026 e 09/2026.
    Restituisce None per una data vuota; solleva ValueError se non la riconosce."""
    s = (text or "").strip()
    if not s:
        return None
    m = (re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", s)
         or re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s))
    if m:
        y, mo, d = m.groups()
    elif m := re.fullmatch(r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})", s):
        y, mo, d = m.groups()
    elif m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", s):
        d, mo, y = m.groups()
    elif m := re.fullmatch(r"(\d{1,2})[/.\-](\d{4})", s):
        mo, y = m.groups()
        d = None
    else:
        raise ValueError(f"Data «{s}» non riconosciuta: usa per esempio 2026-09-17 o 17/09/2026.")
    if (mo and not 1 <= int(mo) <= 12) or (d and not 1 <= int(d) <= 31):
        raise ValueError(f"Data «{s}» non valida.")
    return y + (f"-{int(mo):02d}" if mo else "") + (f"-{int(d):02d}" if d else "")


def connect(clone_name):
    """Apre il database del clone e lo allinea alla sua scheda."""
    profile = read_profile(clone_name)
    path = db_path(clone_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    upgrade(conn)
    sync_profile(conn, profile)
    return conn


NUMBER = r"\d+(?:[.,]\d+)*"


def to_number(t):
    """«1.200» → 1200, «0,5» → 0.5, «2.5» → 2.5: il punto seguito da gruppi di tre cifre separa le migliaia."""
    if "," in t:
        return float(t.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
        return float(t.replace(".", ""))
    return float(t)


def parse_value(text):
    """Un valore numerico scritto a mano o dal modello: «29%», «60-100 %», «1.200 tonnellate», «0,5 kg».
    Restituisce (minimo, massimo, unità); per un valore singolo minimo e massimo coincidono."""
    text = str(text or "").strip()
    if not text:
        return None, None, None
    # Le parole prima del numero («circa il», «tra il») si ignorano; «fino a» vuol dire da zero.
    m = re.fullmatch(rf"([^\d]*?)\s*({NUMBER})\s*(?:(?:-|–|—|a|al|e(?: il| l')?)\s*({NUMBER}))?\s*(.*)", text, re.IGNORECASE)
    if not m or re.search(r"\d", m.group(1)):
        raise ValueError(f"Valore «{text}» non leggibile: scrivi un numero o un intervallo, es. «29 %» o «60-100 %».")
    low = to_number(m.group(2))
    high = to_number(m.group(3)) if m.group(3) else low
    if high < low:
        low, high = high, low
    if re.match(r"fino a", m.group(1).strip(), re.IGNORECASE):
        low = 0.0
    unit = re.sub(r"^(?:il|lo|la|l')\s*", "", m.group(4).strip()) or None
    return low, high, unit


def format_number(x):
    return f"{x:,.10g}".replace(",", "\u2009") if x == int(x) else f"{x:.10g}".replace(".", ",")


def format_value(low, high, unit):
    if low is None:
        return ""
    v = format_number(low) if low == high else f"{format_number(low)}–{format_number(high)}"
    return f"{v} {unit}" if unit else v


# Classificazione delle fonti: nostra e universale, indipendente dai servizi da cui arrivano i testi.
SOURCE_NATURES = {
    "primaria": "il documento o la testimonianza diretta (atto, dati, dichiarazione, studio originale)",
    "secondaria": "chi riporta, commenta o analizza fonti primarie (articolo, saggio, rassegna)",
    "terziaria": "chi riassume altre fonti (enciclopedia, manuale, voce di dizionario)",
}
SOURCE_GENRES = ["articolo", "comunicato", "dichiarazione", "intervista", "documento ufficiale", "atto giudiziario",
                 "dati", "studio scientifico", "saggio o libro", "voce enciclopedica", "lettera o diario",
                 "testimonianza", "pagina web", "post social", "altro"]
SOURCE_FIELDS = ("publisher", "channel", "nature", "language")
OLD_GENRES = {"enciclopedia": "voce enciclopedica", "sentenza": "atto giudiziario", "rapporto": "documento ufficiale",
              "sito web": "pagina web", "web": "pagina web", "catalogo": "saggio o libro", "notizia": "articolo",
              "studio": "studio scientifico"}


def upgrade(conn):
    """Aggiorna i database creati con versioni precedenti di MAVI."""
    if "reported_in" not in [r[1] for r in conn.execute("PRAGMA table_info(sources)")]:
        # Una citazione dentro un articolo è una fonte a sé, «riportata in» quell'articolo.
        conn.execute("ALTER TABLE sources ADD COLUMN reported_in INTEGER REFERENCES sources(id)")
    source_columns = [r[1] for r in conn.execute("PRAGMA table_info(sources)")]
    for col in SOURCE_FIELDS:
        # Chi ha pubblicato, da quale canale è arrivato il testo, natura (primaria/secondaria/terziaria), lingua.
        if col not in source_columns:
            conn.execute(f"ALTER TABLE sources ADD COLUMN {col} TEXT")
    # Generi di versioni precedenti (o nati dai servizi di ricerca) ricondotti alla classificazione di MAVI.
    for old, new in OLD_GENRES.items():
        conn.execute("UPDATE sources SET kind = ? WHERE kind = ?", (new, old))
    columns = [r[1] for r in conn.execute("PRAGMA table_info(assertions)")]
    if "retracted_at" not in columns:
        conn.execute("ALTER TABLE assertions ADD COLUMN retracted_at TEXT")
        conn.execute("ALTER TABLE assertions ADD COLUMN retracted_reason TEXT")
    if "value_min" not in columns:
        # Valori numerici: un numero (minimo = massimo) o un intervallo, con l'unità di misura.
        conn.execute("ALTER TABLE assertions ADD COLUMN value_min REAL")
        conn.execute("ALTER TABLE assertions ADD COLUMN value_max REAL")
        conn.execute("ALTER TABLE assertions ADD COLUMN unit TEXT")
    if "schema_proposal_id" not in [r[1] for r in conn.execute("PRAGMA table_info(proposals)")]:
        conn.execute("ALTER TABLE proposals ADD COLUMN schema_proposal_id INTEGER "
                     "REFERENCES schema_proposals(id)")
    # Date scritte come 20260917 diventano 2026-09-17
    for table, col in (("sources", "date"), ("status_log", "date"),
                       ("assertions", "known_from"), ("assertions", "valid_from")):
        conn.execute(f"""UPDATE {table} SET {col} = substr({col}, 1, 4) || '-' || substr({col}, 5, 2)
                         || '-' || substr({col}, 7, 2)
                         WHERE {col} GLOB '[12][0-9][0-9][0-9][01][0-9][0-3][0-9]'""")
    conn.commit()


def sync_profile(conn, profile):
    """Allinea tipi e relazioni del database alla scheda."""
    for name in profile["tipi_entita"]:
        conn.execute("INSERT OR IGNORE INTO entity_types (name) VALUES (?)", (name,))
    for r in profile["relazioni"]:
        conn.execute(
            """INSERT INTO relation_types (name, definition, inverse, target) VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET definition = excluded.definition,
                                               inverse = excluded.inverse,
                                               target = excluded.target""",
            (r["nome"], r["definizione"], r.get("inversa"), r.get("oggetto", "entita")),
        )
    conn.execute("DELETE FROM relation_sides")
    for r in profile["relazioni"]:
        for side in ("da", "a"):
            for t in r.get(side, []):
                conn.execute("INSERT INTO relation_sides (relation, side, entity_type) VALUES (?, ?, ?)",
                             (r["nome"], side, t))
    conn.commit()


def add_source(conn, label, kind=None, date=None, url=None, publisher=None, channel=None,
               nature=None, language=None):
    """Una fonte. `kind` è il genere del documento; `publisher` chi lo ha pubblicato; `channel` la strada
    da cui è arrivato (a mano, un file, un servizio di ricerca): il canale non è mai la fonte."""
    if nature and nature not in SOURCE_NATURES:
        raise ValueError(f"Natura della fonte «{nature}» non valida: {', '.join(SOURCE_NATURES)}.")
    cur = conn.execute(
        "INSERT INTO sources (label, kind, date, url, publisher, channel, nature, language) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (label, kind, date, url, publisher or None, channel or None, nature or None, language or None),
    )
    return cur.lastrowid


def add_speaker(conn, source_id, entity_id):
    """Indica che nella fonte parla l'entità (persona, istituzione, azienda...)."""
    conn.execute("INSERT INTO source_speakers (source_id, entity_id) VALUES (?, ?)",
                 (source_id, entity_id))


def add_entity(conn, label, type, aliases=()):
    cur = conn.execute("INSERT INTO entities (label, type) VALUES (?, ?)", (label, type))
    for alias in aliases:
        conn.execute("INSERT INTO aliases (entity_id, alias) VALUES (?, ?)", (cur.lastrowid, alias))
    return cur.lastrowid


def find_entity(conn, name):
    """Trova un'entità per nome o per uno dei suoi alias. Restituisce l'id o None."""
    row = conn.execute(
        """SELECT id FROM entities WHERE label = ?
           UNION SELECT entity_id FROM aliases WHERE alias = ?""",
        (name, name),
    ).fetchone()
    return row[0] if row else None


def add_assertion(conn, subject_id, relation, object_id, source_id, *,
                  claim_type, status="da_verificare", valid_from=None, valid_to=None,
                  known_from=None, excerpt=None, is_manual=0, reason=None,
                  object_assertion_id=None, value=None):
    low, high, unit = parse_value(value)
    cur = conn.execute(
        """INSERT INTO assertions (subject_id, relation, object_id, object_assertion_id,
               valid_from, valid_to, known_from, source_id, excerpt, claim_type, status, is_manual)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (subject_id, relation, object_id, object_assertion_id, valid_from, valid_to,
         known_from, source_id, excerpt, claim_type, status, is_manual),
    )
    aid = cur.lastrowid
    if low is not None:
        conn.execute("UPDATE assertions SET value_min = ?, value_max = ?, unit = ? WHERE id = ?",
                     (low, high, unit, aid))
    first_date = known_from or conn.execute(
        "SELECT date FROM sources WHERE id = ?", (source_id,)).fetchone()[0]
    conn.execute(
        "INSERT INTO status_log (assertion_id, status, date, reason) VALUES (?, ?, ?, ?)",
        (aid, status, first_date, reason or "Inserimento"),
    )
    return aid


def add_assertion_about(conn, subject_id, relation, target_assertion_id, source_id, **kw):
    """Asserzione il cui oggetto è un'altra asserzione (es. una smentita)."""
    return add_assertion(conn, subject_id, relation, None, source_id,
                         object_assertion_id=target_assertion_id, **kw)


def set_status(conn, assertion_id, status, date, reason):
    """Cambia lo stato di un'asserzione registrando data e motivo. Nulla viene sovrascritto."""
    conn.execute("UPDATE assertions SET status = ? WHERE id = ?", (status, assertion_id))
    conn.execute(
        "INSERT INTO status_log (assertion_id, status, date, reason) VALUES (?, ?, ?, ?)",
        (assertion_id, status, date, reason),
    )


def add_conflict(conn, assertion_a, assertion_b, note=None):
    cur = conn.execute(
        "INSERT INTO conflicts (assertion_a, assertion_b, note) VALUES (?, ?, ?)",
        (assertion_a, assertion_b, note),
    )
    return cur.lastrowid


def change_status(conn, assertion_id, status, date, reason):
    """Cambio di stato chiesto dalla persona: controlla i dati, registra e salva."""
    if status not in STATUSES:
        raise ValueError(f"Stato «{status}» non valido.")
    if not (reason or "").strip():
        raise ValueError("Scrivi il motivo del cambio di stato: resterà nella storia dell'affermazione.")
    row = conn.execute("SELECT status FROM assertions WHERE id = ? AND retracted_at IS NULL",
                       (assertion_id,)).fetchone()
    if not row:
        raise ValueError("Affermazione inesistente o ritirata.")
    if row[0] == status:
        raise ValueError("L'affermazione ha già questo stato.")
    set_status(conn, assertion_id, status, normalize_date(date) or today(), reason.strip())
    conn.commit()


def retract(conn, assertion_id, reason, date=None):
    """Ritira un'affermazione inserita per errore (la fonte non dice questo).
    Non la cancella: esce dal grafo ma resta nel database con data e motivo.
    Diverso da «smentita», che vuol dire: la fonte lo dice, ma è falso."""
    if not (reason or "").strip():
        raise ValueError("Scrivi il motivo del ritiro.")
    if not conn.execute("SELECT 1 FROM assertions WHERE id = ? AND retracted_at IS NULL",
                        (assertion_id,)).fetchone():
        raise ValueError("Affermazione inesistente o già ritirata.")
    if conn.execute("SELECT 1 FROM assertions WHERE object_assertion_id = ? AND retracted_at IS NULL",
                    (assertion_id,)).fetchone():
        raise ValueError("Altre affermazioni la riguardano (per esempio una smentita): ritira prima quelle.")
    conn.execute("UPDATE assertions SET retracted_at = ?, retracted_reason = ? WHERE id = ?",
                 (normalize_date(date) or today(), reason.strip(), assertion_id))
    conn.commit()


def merge_entities(conn, source_id, target_id):
    """Unisce un'entità doppia nell'altra: affermazioni, voci e nomi alternativi passano
    a quella che resta, e il nome di quella che sparisce diventa un suo nome alternativo.
    L'unione resta registrata in entity_merges."""
    if source_id == target_id:
        raise ValueError("È la stessa entità.")
    src = conn.execute("SELECT label, type FROM entities WHERE id = ?", (source_id,)).fetchone()
    tgt = conn.execute("SELECT label, type FROM entities WHERE id = ?", (target_id,)).fetchone()
    if not src or not tgt:
        raise ValueError("Entità inesistente.")
    if conn.execute(
        """SELECT 1 FROM assertions WHERE retracted_at IS NULL AND
           ((subject_id = ? AND object_id = ?) OR (subject_id = ? AND object_id = ?))""",
        (source_id, target_id, target_id, source_id)).fetchone():
        raise ValueError("Le due entità sono collegate da un'affermazione: unendole, diventerebbe "
                         "un'affermazione su se stessa. Ritirala prima, se è un errore.")
    problems = set()
    for a in conn.execute("SELECT relation, subject_id, object_id FROM assertions "
                          "WHERE subject_id = ? OR object_id = ?", (source_id, source_id)):
        for side, col, word in (("da", "subject_id", "soggetto"), ("a", "object_id", "oggetto")):
            if a[col] != source_id:
                continue
            allowed = [r[0] for r in conn.execute(
                "SELECT entity_type FROM relation_sides WHERE relation = ? AND side = ?", (a["relation"], side))]
            if allowed and tgt["type"] not in allowed:
                problems.add(f"«{a['relation']}» non ammette {tgt['type']} come {word}")
    if problems:
        raise ValueError(f"Non si possono unire: «{tgt['label']}» è {tgt['type']}, ma "
                         + "; ".join(sorted(problems)) + ".")
    conn.execute("UPDATE assertions SET subject_id = ? WHERE subject_id = ?", (target_id, source_id))
    conn.execute("UPDATE assertions SET object_id = ? WHERE object_id = ?", (target_id, source_id))
    conn.execute("""INSERT OR IGNORE INTO source_speakers (source_id, entity_id)
                    SELECT source_id, ? FROM source_speakers WHERE entity_id = ?""", (target_id, source_id))
    conn.execute("DELETE FROM source_speakers WHERE entity_id = ?", (source_id,))
    conn.execute("UPDATE aliases SET entity_id = ? WHERE entity_id = ?", (target_id, source_id))
    if src["label"].lower() != tgt["label"].lower():
        conn.execute("INSERT OR IGNORE INTO aliases (entity_id, alias) VALUES (?, ?)", (target_id, src["label"]))
    conn.execute("INSERT INTO entity_merges (merged_label, merged_type, into_id, date) VALUES (?, ?, ?, ?)",
                 (src["label"], src["type"], target_id, today()))
    conn.execute("DELETE FROM entities WHERE id = ?", (source_id,))
    conn.commit()


def today():
    import datetime
    return datetime.date.today().isoformat()


def graph(conn):
    """Restituisce nodi, archi e date significative, pronti per l'interfaccia."""
    aliases = {}
    for r in conn.execute("SELECT entity_id, alias FROM aliases ORDER BY alias"):
        aliases.setdefault(r["entity_id"], []).append(r["alias"])
    nodes = [dict(r, aliases=aliases.get(r["id"], []))
             for r in conn.execute("SELECT id, label, type FROM entities")]

    edges = {}
    for r in conn.execute(
        """SELECT a.id, a.subject_id, a.relation, a.object_id, a.object_assertion_id,
                  a.valid_from, a.valid_to,
                  COALESCE(a.known_from, src.date) AS known_from,
                  a.excerpt, a.claim_type, a.status, a.is_manual, a.source_id,
                  a.value_min, a.value_max, a.unit,
                  rt.definition AS relation_definition,
                  s.label AS subject, o.label AS object,
                  src.label AS source_label, src.kind AS source_kind,
                  src.date AS source_date, src.url AS source_url, rep.label AS reported_in,
                  COALESCE(src.publisher, rep.publisher) AS source_publisher,
                  COALESCE(src.nature, rep.nature) AS source_nature,
                  COALESCE(src.channel, rep.channel) AS source_channel,
                  COALESCE(src.language, rep.language) AS source_language,
                  -- La radice: per l'indipendenza contano l'editore (o il documento) da cui tutto proviene.
                  CASE WHEN rep.id IS NOT NULL THEN COALESCE(rep.publisher, rep.label)
                       ELSE COALESCE(src.publisher, src.label) END AS source_root
           FROM assertions a
           JOIN relation_types rt ON rt.name = a.relation
           JOIN entities s ON s.id = a.subject_id
           LEFT JOIN entities o ON o.id = a.object_id
           JOIN sources src ON src.id = a.source_id
           LEFT JOIN sources rep ON rep.id = src.reported_in
           WHERE a.retracted_at IS NULL
           ORDER BY a.id"""
    ):
        edges[r["id"]] = dict(r, conflicts=[], history=[], targeted_by=[], speakers=[],
                              value=format_value(r["value_min"], r["value_max"], r["unit"]))

    retracted = [dict(r) for r in conn.execute(
        """SELECT a.id, s.label AS subject, a.relation, COALESCE(o.label, '[affermazione]') AS object,
                  src.label AS source_label, a.retracted_at, a.retracted_reason
           FROM assertions a JOIN entities s ON s.id = a.subject_id
           LEFT JOIN entities o ON o.id = a.object_id JOIN sources src ON src.id = a.source_id
           WHERE a.retracted_at IS NOT NULL ORDER BY a.retracted_at DESC, a.id DESC""")]

    speakers = {}
    for r in conn.execute(
        """SELECT ss.source_id, e.id, e.label FROM source_speakers ss
           JOIN entities e ON e.id = ss.entity_id ORDER BY e.label"""
    ):
        speakers.setdefault(r["source_id"], []).append({"id": r["id"], "label": r["label"]})
    for e in edges.values():
        e["speakers"] = speakers.get(e["source_id"], [])

    # Le asserzioni su altre asserzioni prendono come oggetto il riassunto della tesi.
    for e in edges.values():
        if e["object_assertion_id"] in edges:
            t = edges[e["object_assertion_id"]]
            e["object"] = f'[{t["subject"]} — {t["relation"]} → {t["object"]}]'
            t["targeted_by"].append({"id": e["id"], "relation": e["relation"],
                                     "subject": e["subject"], "source_label": e["source_label"]})

    for r in conn.execute(
        "SELECT assertion_id, status, date, reason FROM status_log ORDER BY date, id"
    ):
        if r["assertion_id"] in edges:
            edges[r["assertion_id"]]["history"].append(
                {"status": r["status"], "date": r["date"], "reason": r["reason"]})

    def summary(e):
        return f'{e["subject"]} — {e["relation"]} → {e["object"]} ({e["source_label"]})'

    for c in conn.execute("SELECT assertion_a, assertion_b, note FROM conflicts"):
        if c["assertion_a"] not in edges or c["assertion_b"] not in edges:
            continue
        a, b = edges[c["assertion_a"]], edges[c["assertion_b"]]
        a["conflicts"].append({"id": b["id"], "with": summary(b), "note": c["note"]})
        b["conflicts"].append({"id": a["id"], "with": summary(a), "note": c["note"]})

    dates = sorted({d for e in edges.values()
                    for d in [e["known_from"]] + [h["date"] for h in e["history"]] if d})

    result = {"nodes": nodes, "edges": list(edges.values()), "dates": dates, "retracted": retracted}
    result["weak"] = weak_points(result["edges"])
    result["composition"] = composition(conn)
    return result


def composition(conn):
    """Da dove viene ciò che si sa: le fonti (le radici, non le citazioni al loro interno) che
    sostengono almeno un'affermazione nel grafo, contate per editore, genere, natura, lingua e canale.
    Gli avvisi rendono visibili le distorsioni: MAVI non le corregge, le mostra."""
    rows = conn.execute(
        """SELECT DISTINCT root.id, COALESCE(root.publisher, root.label) AS publisher, root.kind, root.nature,
                  root.language, root.channel
           FROM assertions a JOIN sources src ON src.id = a.source_id
           JOIN sources root ON root.id = COALESCE(src.reported_in, src.id)
           WHERE a.retracted_at IS NULL""").fetchall()
    n = len(rows)
    count = lambda key, empty: sorted(
        {v: sum(1 for r in rows if (r[key] or empty) == v) for v in {r[key] or empty for r in rows}}.items(),
        key=lambda kv: (-kv[1], kv[0]))
    by = {"editore": count("publisher", "non indicato"), "genere": count("kind", "non indicato"),
          "natura": count("nature", "non classificata"), "lingua": count("language", "non indicata"),
          "canale": count("channel", "inserita a mano")}
    warnings = []
    if n:
        natures = dict(by["natura"])
        if natures.get("non classificata", 0) > n / 2:
            warnings.append("Più di metà delle fonti non è classificata come primaria, secondaria o terziaria.")
        elif not natures.get("primaria"):
            warnings.append("Nessuna fonte primaria: tutto ciò che sai è riportato da altri.")
        if n >= 4 and by["editore"][0][1] / n >= 0.5:
            warnings.append(f"Metà delle fonti o più viene da un solo editore: {by['editore'][0][0]}.")
        known = [l for l, _ in by["lingua"] if l != "non indicata"]
        if n >= 3 and len(known) == 1:
            warnings.append(f"Tutte le fonti di lingua nota sono in {known[0]}.")
        if n >= 3 and len(by["canale"]) == 1 and by["canale"][0][0] != "inserita a mano":
            warnings.append(f"Tutte le fonti sono arrivate dallo stesso canale: {by['canale'][0][0]}.")
    return {"fonti": n, "per": by, "avvisi": warnings}


def weak_points(edges):
    """Cosa merita di essere approfondito: calcolato dalle regole, senza modelli linguistici."""
    def text(e):
        when = f' [{e["valid_from"]}]' if e["valid_from"] else ""
        return f'{e["subject"]} — {e["relation"]} → {e["object"]}{when}'

    facts = [e for e in edges if not e["object_assertion_id"]]
    by_triple = {}
    for e in facts:
        by_triple.setdefault((e["subject_id"], e["relation"], e["object_id"]), []).append(e)

    single = []
    for group in by_triple.values():
        roots = {e["source_root"] for e in group}
        if len(roots) == 1:
            single += [e for e in group if e["status"] == "da_verificare"]

    contested = [e for e in edges if e["targeted_by"] and e["status"] == "da_verificare"]

    open_conflicts, seen = [], set()
    by_id = {e["id"]: e for e in edges}
    for e in edges:
        for c in e["conflicts"]:
            pair = tuple(sorted((e["id"], c["id"])))
            other = by_id[c["id"]]
            if pair in seen or "smentita" in (e["status"], other["status"]):
                continue
            seen.add(pair)
            open_conflicts.append({"id": e["id"], "testo": f'{text(e)}  ⟷  {text(other)}'})

    # Lo stesso legame con valori che non si sovrappongono (es. 29 % e 60-100 % nello stesso prodotto).
    discordant = []
    for group in by_triple.values():
        valued = [e for e in group if e["value_min"] is not None]
        for i, a in enumerate(valued):
            for b in valued[i + 1:]:
                if (a["unit"] or "") == (b["unit"] or "") and (a["value_max"] < b["value_min"] or b["value_max"] < a["value_min"]):
                    discordant.append({"id": a["id"], "testo": f'{text(a)}: {a["value"]} ({a["source_label"]})  ⟷  '
                                                             f'{b["value"]} ({b["source_label"]})'})

    voiceless = [e for e in facts if e["claim_type"] in ("interpretazione", "ipotesi")
                 and not e["speakers"] and not e["is_manual"]]

    def items(lst):
        return [{"id": e["id"], "testo": f'{text(e)} ({e["source_label"]})'} for e in lst]

    return [c for c in [
        {"titolo": "Conflitti aperti", "spiegazione": "Versioni incompatibili, nessuna delle due smentita.",
         "voci": open_conflicts},
        {"titolo": "Valori discordanti", "spiegazione": "Lo stesso legame con numeri che non si sovrappongono.",
         "voci": discordant},
        {"titolo": "Contestazioni senza esito", "spiegazione": "Qualcuno le contesta, ma sono ancora da verificare.",
         "voci": items(contested)},
        {"titolo": "Una sola fonte", "spiegazione": "Da verificare e sostenute da un'unica fonte: cercane una seconda.",
         "voci": items(single)},
        {"titolo": "Interpretazioni senza voce", "spiegazione": "Giudizi o ipotesi di cui non si sa chi li sostiene.",
         "voci": items(voiceless)},
    ] if c["voci"]]


def add_note(conn, kind, text):
    text = (text or "").strip()
    if not text:
        raise ValueError("Scrivi il testo della nota.")
    try:
        nid = conn.execute("INSERT INTO notes (kind, text, created_at) VALUES (?, ?, ?)", (kind, text, today())).lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("Tipo di nota non valido: ipotesi, domanda o nota.")
    conn.commit()
    return nid


def set_note_state(conn, nid, state):
    try:
        n = conn.execute("UPDATE notes SET state = ?, updated_at = ? WHERE id = ?", (state, today(), nid)).rowcount
    except sqlite3.IntegrityError:
        raise ValueError("Stato non valido: aperta, confermata o scartata.")
    if not n:
        raise ValueError("Nota inesistente.")
    conn.commit()


def notes(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM notes ORDER BY state = 'aperta' DESC, id DESC")]
