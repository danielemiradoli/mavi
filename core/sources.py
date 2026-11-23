"""Fonti aperte: cercare testi su un tema e portarli nella coda di revisione.

Regola: il motore conosce solo documenti, non servizi. Ogni canale (un servizio di ricerca, un file
del PC, un testo incollato) consegna lo stesso contratto:
    {"titolo", "url", "data", "editore", "genere", "natura", "lingua", "canale", "estratto"}
dove `editore` è chi ha pubblicato il testo (la fonte vera) e `canale` è solo la strada da cui è
arrivato. Genere e natura usano la classificazione di MAVI (database.SOURCE_GENRES, SOURCE_NATURES):
il canale li propone quando li conosce con certezza, altrimenti li lascia vuoti per la persona.
L'ordine dei risultati è quello di ciascun servizio: la pagina lo dichiara.
`fetch_text` recupera il testo completo da dare all'estrazione.

- Wikipedia (italiano e inglese): enciclopedia, senza chiave.
- GDELT: notizie da tutto il mondo degli ultimi tre mesi circa, senza chiave (una richiesta ogni 5 secondi).
- Tavily: ricerca sul web, chiave gratuita (1000 ricerche al mese, senza carta di credito).
- OpenAlex: articoli scientifici, chiave gratuita.

MAVI non cerca da solo: propone, e la persona sceglie quali testi leggere.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .extraction import limit, settings

USER_AGENT = "MAVI/0.9 (prototipo di ricerca; https://github.com/danielemiradoli/mavi)"
BASES = {                       # sostituibili nelle prove
    "wikipedia": "https://{lang}.wikipedia.org/w/api.php",
    "gdelt": "https://api.gdeltproject.org/api/v2/doc/doc",
    "tavily": "https://api.tavily.com",
    "openalex": "https://api.openalex.org",
}
LANGUAGES = {"it": "italiano", "en": "inglese", "fr": "francese", "de": "tedesco", "es": "spagnolo",
             "pt": "portoghese", "nl": "olandese", "pl": "polacco", "ro": "rumeno", "ru": "russo",
             "zh": "cinese", "ja": "giapponese", "ar": "arabo", "tr": "turco"}
LANGUAGES.update({"italian": "italiano", "english": "inglese", "french": "francese", "german": "tedesco",
                  "spanish": "spagnolo", "portuguese": "portoghese", "dutch": "olandese", "polish": "polacco",
                  "romanian": "rumeno", "russian": "russo", "chinese": "cinese", "japanese": "giapponese",
                  "arabic": "arabo", "turkish": "turco"})


def language(code):
    return LANGUAGES.get((code or "").strip().lower(), (code or "").strip().lower())


def domain(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def item(**kw):
    """Un risultato nel formato comune: i campi mancanti restano vuoti."""
    base = dict.fromkeys(("titolo", "url", "data", "editore", "genere", "natura", "lingua", "canale", "estratto"), "")
    return {**base, **{k: v for k, v in kw.items() if v is not None}}


class SourceError(Exception):
    """Una fonte non risponde o rifiuta la richiesta."""


def keys():
    return settings().get("fonti", {})


def http(url, body=None, headers=None, timeout=30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json",
        **({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        hint = {401: "chiave non valida", 403: "accesso negato", 429: "troppe richieste: attendi qualche secondo"}
        raise SourceError(f"errore {e.code}{': ' + hint[e.code] if e.code in hint else ''}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SourceError(f"non raggiungibile ({e})")
    except json.JSONDecodeError:
        raise SourceError("risposta non leggibile")


def clean(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def gdelt_date(s):
    """«20260917T120000Z» → «2026-09-17»."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})", s or "")
    return f"{m[1]}-{m[2]}-{m[3]}" if m else ""


# --- Ricerca -----------------------------------------------------------------------------------

def parse_wikipedia(reply, lang):
    # Una voce enciclopedica è per definizione una fonte terziaria.
    return [item(titolo=r["title"], url=f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(r['title'].replace(' ', '_'))}",
                 data=(r.get("timestamp") or "")[:10], estratto=clean(r.get("snippet")) + "…",
                 editore=f"Wikipedia ({lang})", genere="voce enciclopedica", natura="terziaria",
                 lingua=language(lang), canale="Wikipedia")
            for r in reply.get("query", {}).get("search", [])]


def search_wikipedia(query, n=6, langs=("it", "en")):
    out = []
    for lang in langs:
        url = BASES["wikipedia"].format(lang=lang) + "?" + urllib.parse.urlencode({
            "action": "query", "list": "search", "srsearch": query, "srlimit": n,
            "format": "json", "utf8": 1})
        out += parse_wikipedia(http(url), lang)
    return out


def parse_gdelt(reply):
    # GDELT indicizza articoli di testate: genere noto, natura da valutare (un articolo può riportare un documento
    # primario o commentarlo).
    return [item(titolo=a.get("title", ""), url=a.get("url", ""), data=gdelt_date(a.get("seendate")),
                 editore=a.get("domain") or domain(a.get("url", "")), genere="articolo",
                 lingua=language(a.get("language")), canale="GDELT",
                 estratto=a.get("sourcecountry", ""))
            for a in reply.get("articles", [])]


_last_gdelt = [0.0]


def search_gdelt(query, n=10):
    # GDELT chiede al massimo una richiesta ogni 5 secondi.
    wait = 5.2 - (time.time() - _last_gdelt[0])
    if wait > 0:
        time.sleep(wait)
    _last_gdelt[0] = time.time()
    q = f'"{query}"' if " " in query and '"' not in query else query
    url = BASES["gdelt"] + "?" + urllib.parse.urlencode({
        "query": q, "mode": "ArtList", "format": "json", "maxrecords": n, "sort": "HybridRel"})
    return parse_gdelt(http(url))


def parse_tavily(reply):
    # Il web contiene di tutto: genere e natura li decide la persona.
    return [item(titolo=r.get("title", ""), url=r["url"], data=(r.get("published_date") or "")[:10],
                 editore=domain(r["url"]), canale="Tavily", estratto=(r.get("content") or "")[:400])
            for r in reply.get("results", [])]


def search_tavily(query, n=8):
    key = keys().get("tavily", {}).get("chiave")
    if not key:
        raise SourceError("manca la chiave in impostazioni.json")
    reply = http(BASES["tavily"] + "/search", {"query": query, "max_results": n, "search_depth": "basic"},
                 {"Authorization": f"Bearer {key}"})
    return parse_tavily(reply)


def abstract(inverted):
    """OpenAlex dà il riassunto come indice parola → posizioni: lo si ricompone."""
    if not inverted:
        return ""
    words = sorted((pos, w) for w, places in inverted.items() for pos in places)
    return " ".join(w for _, w in words)


def parse_openalex(reply):
    out = []
    for w in reply.get("results", []):
        loc = w.get("primary_location") or {}
        venue = (loc.get("source") or {}).get("display_name") or ""
        text = abstract(w.get("abstract_inverted_index"))
        # Uno studio può essere originale (primaria) o una rassegna (secondaria): lo decide la persona.
        out.append(dict(item(titolo=w.get("display_name") or w.get("title") or "",
                             url=w.get("doi") or loc.get("landing_page_url") or w.get("id", ""),
                             data=w.get("publication_date") or str(w.get("publication_year") or ""),
                             editore=venue, genere="studio scientifico", lingua=language(w.get("language")),
                             canale="OpenAlex", estratto=text[:400]), testo=text))
    return out


def search_openalex(query, n=8):
    key = keys().get("openalex", {}).get("chiave")
    if not key:
        raise SourceError("manca la chiave in impostazioni.json")
    url = BASES["openalex"] + "/works?" + urllib.parse.urlencode({"search": query, "per_page": n, "api_key": key})
    return parse_openalex(http(url))


CONNECTORS = {
    "wikipedia": {"nome": "Wikipedia", "descrizione": "Enciclopedia, in italiano e inglese", "chiave": False,
                  "cerca": search_wikipedia},
    "gdelt": {"nome": "GDELT", "descrizione": "Notizie da tutto il mondo, ultimi tre mesi circa", "chiave": False,
              "cerca": search_gdelt},
    "tavily": {"nome": "Web (Tavily)", "descrizione": "Ricerca sul web: articoli, documenti, siti ufficiali",
               "chiave": True, "cerca": search_tavily},
    "openalex": {"nome": "OpenAlex", "descrizione": "Articoli scientifici (solo il riassunto)", "chiave": True,
                 "cerca": search_openalex},
}


def available():
    k = keys()
    return [{"id": cid, "nome": c["nome"], "descrizione": c["descrizione"],
             "attiva": not c["chiave"] or bool(k.get(cid, {}).get("chiave"))}
            for cid, c in CONNECTORS.items()]


def search(query, which):
    """Cerca su ogni fonte scelta. Una fonte che non risponde non blocca le altre."""
    results, errors = [], {}
    for cid in which:
        if cid not in CONNECTORS:
            continue
        try:
            results += [dict(r, connettore=cid) for r in CONNECTORS[cid]["cerca"](query)]
        except SourceError as e:
            errors[CONNECTORS[cid]["nome"]] = str(e)
    return results, errors


# --- Testo completo ------------------------------------------------------------------------------

def fetch_wikipedia(url):
    m = re.match(r"https?://(\w+)\.wikipedia\.org/wiki/(.+)", url)
    lang, title = m[1], urllib.parse.unquote(m[2]).replace("_", " ")
    reply = http(BASES["wikipedia"].format(lang=lang) + "?" + urllib.parse.urlencode({
        "action": "query", "prop": "extracts|revisions", "explaintext": 1, "titles": title,
        "rvprop": "timestamp", "format": "json", "redirects": 1}))
    page = next(iter(reply.get("query", {}).get("pages", {}).values()), {})
    if "extract" not in page:
        raise SourceError("voce non trovata")
    # I titoli di sezione («== Storia ==») diventano paragrafi a sé.
    return re.sub(r"\n*(=+) *(.+?) *=+\n*", r"\n\n\2\n\n", page["extract"]).strip()


def download(url):
    """L'HTML di una pagina, decodificato con la codifica che dichiara."""
    req = urllib.request.Request(url, headers={"User-Agent": f"Mozilla/5.0 (compatible; {USER_AGENT})",
                                               "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read(5_000_000)
            charset = r.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as e:
        raise SourceError(f"la pagina risponde con l'errore {e.code}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SourceError(f"pagina non raggiungibile ({e})")
    return raw.decode(charset, "replace")


def fetch_page(url):
    """Testo principale di una pagina web, senza menu né pubblicità."""
    key = keys().get("tavily", {}).get("chiave")
    if key:
        try:
            reply = http(BASES["tavily"] + "/extract", {"urls": [url]}, {"Authorization": f"Bearer {key}"}, timeout=60)
            text = ((reply.get("results") or [{}])[0].get("raw_content") or "").strip()
            if text:
                return text
        except SourceError:
            pass
    try:
        import trafilatura
    except ImportError:
        raise SourceError("manca il componente trafilatura: esegui di nuovo esegui.bat")
    html = download(url)
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True) if html else None
    if not text:
        raise SourceError("impossibile leggere il testo della pagina (sito protetto o pagina vuota)")
    return text


def fetch_text(item):
    """Il testo da dare all'estrazione e un'eventuale nota se è stato troncato."""
    if item.get("testo"):
        text = item["testo"]
    elif "wikipedia.org/wiki/" in item["url"]:
        text = fetch_wikipedia(item["url"])
    else:
        text = fetch_page(item["url"])
    most = limit("caratteri_per_testo")
    if len(text) > most:
        cut = text.rfind("\n\n", 0, most)
        return text[:cut if cut > most // 2 else most], len(text)
    return text, None


# --- File del PC -----------------------------------------------------------------------------------

def read_file(name, data):
    """Testo di un file caricato dalla persona: PDF, Word (.docx), pagina web salvata, testo semplice."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "pdf":
        import io
        from pypdf import PdfReader
        try:
            text = "\n\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
        except Exception as e:                       # PDF danneggiato o protetto
            raise SourceError(f"PDF non leggibile ({e})")
        if not text.strip():
            raise SourceError("il PDF non contiene testo (forse è una scansione: serve il riconoscimento dei caratteri)")
        return text
    if ext == "docx":
        import io
        import zipfile
        from xml.etree import ElementTree
        try:
            xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml")
        except (zipfile.BadZipFile, KeyError):
            raise SourceError("file Word non leggibile")
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paras = ["".join(t.text or "" for t in p.iter(w + "t")) for p in ElementTree.fromstring(xml).iter(w + "p")]
        return "\n\n".join(p for p in paras if p.strip())
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            raw = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if ext in ("html", "htm"):
        import trafilatura
        return trafilatura.extract(raw, include_tables=True) or clean(raw)
    if ext in ("txt", "md", "csv", ""):
        return raw
    raise SourceError(f"formato .{ext} non ancora supportato (PDF, Word .docx, HTML, testo)")


def file_item(name, data):
    text = read_file(name, data).strip()
    if not text:
        raise SourceError("il file è vuoto")
    title = name.rsplit(".", 1)[0] if "." in name else name
    return dict(item(titolo=title, url=f"file:{name}", canale="file del PC", estratto=text[:300] + "…"), testo=text)
