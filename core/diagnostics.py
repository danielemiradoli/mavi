"""Stato di MAVI: controlla in un colpo che tutto ciò che serve sia al suo posto.

Ogni controllo restituisce {"gruppo", "nome", "esito": "ok" | "avviso" | "errore", "dettaglio"}.
Le chiavi non vengono mai mostrate: si dice solo se ci sono e se funzionano.
"""
import importlib
import json
import sys
import urllib.error
import urllib.request

from . import extraction, sources
from .database import connect, read_profile


def check(group, name, fn):
    try:
        result = fn()
        state, detail = result if isinstance(result, tuple) else ("ok", result)
    except Exception as e:                      # un controllo che fallisce non ferma gli altri
        state, detail = "errore", str(e) or e.__class__.__name__
    return {"gruppo": group, "nome": name, "esito": state, "dettaglio": detail}


def python():
    v = sys.version_info
    if v < (3, 10):
        return "errore", f"Python {v.major}.{v.minor}: serve 3.10 o superiore"
    return f"Python {v.major}.{v.minor}.{v.micro}"


def package(name, why):
    def run():
        try:
            mod = importlib.import_module(name)
        except ImportError:
            return "errore", f"non installato ({why}): fai doppio clic su esegui.bat"
        return f"installato {getattr(mod, '__version__', '')}".strip()
    return run


def settings_file():
    if not extraction.SETTINGS.exists():
        return "errore", "manca impostazioni.json: copia impostazioni.esempio.json e inserisci la chiave"
    try:
        json.loads(extraction.SETTINGS.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        return "errore", f"impostazioni.json non è scritto bene (riga {e.lineno}): controlla virgole e virgolette"
    return "presente e leggibile"


def model():
    prov = extraction.provider()
    name = extraction.describe(prov)
    if prov["tipo"] == "ollama":
        with urllib.request.urlopen(f'{prov["indirizzo"]}/api/tags', timeout=10) as r:
            models = [m["name"] for m in json.loads(r.read()).get("models", [])]
        if not any(m == prov["modello"] or m.split(":")[0] == prov["modello"] for m in models):
            return "errore", f"{name}: Ollama risponde ma il modello non è installato (ollama pull {prov['modello']})"
        return f"{name}: pronto"
    if not prov.get("chiave"):
        return "errore", f"{name}: manca la chiave in impostazioni.json"
    # L'elenco dei modelli verifica chiave e connessione senza consumare richieste di estrazione.
    req = urllib.request.Request(f'{prov["indirizzo"].rstrip("/")}/models', headers={
        "Authorization": f'Bearer {prov["chiave"]}', "User-Agent": "MAVI/0.9"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            ids = [m.get("id") for m in json.loads(r.read()).get("data", [])]
    except urllib.error.HTTPError as e:
        hint = {401: "la chiave non è valida", 403: "accesso negato"}.get(e.code, "")
        return "errore", f"{name}: errore {e.code}{' — ' + hint if hint else ''}"
    if ids and prov["modello"] not in ids:
        return "avviso", f"{name}: la chiave funziona, ma il modello non è nell'elenco del servizio"
    return f"{name}: la chiave funziona"


def service(cid):
    def run():
        c = sources.CONNECTORS[cid]
        if c["chiave"] and not sources.keys().get(cid, {}).get("chiave"):
            return "avviso", "spento: manca la chiave (facoltativa) in impostazioni.json"
        results = c["cerca"]("Leonardo da Vinci")
        if not results:
            return "avviso", "risponde, ma senza risultati"
        return f"risponde ({len(results)} risultati di prova)" + (" · consuma 1 ricerca" if c["chiave"] else "")
    return run


def web_reading():
    sources.fetch_text({"url": "https://it.wikipedia.org/wiki/Leonardo_da_Vinci"})
    return "Wikipedia leggibile"


def clone(name):
    def run():
        conn = connect(name)
        try:
            n = conn.execute("SELECT COUNT(*) FROM assertions WHERE retracted_at IS NULL").fetchone()[0]
            q = conn.execute("SELECT COUNT(*) FROM proposals WHERE state = 'in_attesa'").fetchone()[0]
        finally:
            conn.close()
        return f"«{read_profile(name)['nome']}»: {n} affermazioni, {q} proposte in attesa"
    return run


def status(clone_name):
    checks = [
        check("Ambiente", "Python", python),
        check("Ambiente", "Server (FastAPI)", package("fastapi", "il server di MAVI")),
        check("Ambiente", "Lettura pagine web (trafilatura)", package("trafilatura", "per leggere le pagine web")),
        check("Ambiente", "Lettura PDF (pypdf)", package("pypdf", "per leggere i PDF")),
        check("Modello", "impostazioni.json", settings_file),
        check("Modello", "Modello per l'estrazione", model),
        check("Modello", "Limiti tecnici", lambda: ", ".join(f"{k.replace('_', ' ')}: {extraction.limit(k)}"
                                                         for k in extraction.LIMITS)),
        check("Clone", "Clone attivo", clone(clone_name)),
    ]
    for cid, c in sources.CONNECTORS.items():
        checks.append(check("Fonti", c["nome"], service(cid)))
    checks.append(check("Fonti", "Lettura del testo completo", web_reading))
    return checks
