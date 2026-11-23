"""Dati di esempio: lo scandalo europeo della carne di cavallo (2013).

Ricrea da zero il database del clone "carne_cavallo".
Note:
- il campo `excerpt` contiene brevi sintesi scritte a mano, non citazioni letterali;
- la ricostruzione della DGCCRF non è datata: riporta la sentenza del 16 aprile 2019,
  quindi la si considera nota da allora.
"""

from core.database import (add_assertion, add_assertion_about, add_conflict, add_entity,
                           add_source, add_speaker, connect, db_path, set_status)

CLONE = "carne_cavallo"
WIKI = "https://en.wikipedia.org/wiki/2013_horse_meat_scandal"
FOODNAV = "https://www.foodnavigator.com/Article/2013/01/28/Horse-meat-found-to-come-from-Poland-by-FSAI/"
FOX = ("https://www.foxnews.com/world/polish-official-no-evidence-yet-that-horse-meat-"
       "in-british-irish-burgers-came-from-poland")
RFERL = "https://www.rferl.org/a/ikea-horsemeat-czech-meatballs/24912400.html"
DGCCRF = "https://www.economie.gouv.fr/dgccrf/pur-boeuf-au-gout-cheval-retour-sur-fraude-denvergure"
QC = ("https://www.quechoisir.org/actualite-fraude-a-la-viande-de-cheval-des-peines-de-"
      "prison-ferme-a-l-issue-du-proces-spanghero-n65959/")
SENTENZA = "2019-04-16"

db_path(CLONE).unlink(missing_ok=True)
conn = connect(CLONE)

# --- Fonti: chi afferma che cosa (url = dove l'affermazione è documentata) ---
src = {
    "fsai":     add_source(conn, "FSAI, annuncio dei risultati dei test", "comunicato", "2013-01-15", WIKI),
    "coveney":  add_source(conn, "Simon Coveney, dichiarazione sull'origine polacca", "dichiarazione", "2013-01-28", FOODNAV),
    "naze":     add_source(conn, "Jaroslaw Naze, Ispettorato veterinario polacco", "dichiarazione", "2013-01-31", FOX),
    "findus":   add_source(conn, "Findus, annuncio sulle lasagne", "comunicato", "2013-02-07", WIKI),
    "lehagre":  add_source(conn, "Erick Lehagre (Comigel), intervista ad AFP", "intervista", "2013-02-09", WIKI),
    "hamon11":  add_source(conn, "Benoît Hamon, dichiarazione sulla filiera", "dichiarazione", "2013-02-11", WIKI),
    "hamon14":  add_source(conn, "Governo francese, esito della prima indagine", "dichiarazione", "2013-02-14", WIKI),
    "spangh":   add_source(conn, "Spanghero, replica", "dichiarazione", "2013-02-14", WIKI),
    "romania":  add_source(conn, "Governo rumeno, dichiarazione", "dichiarazione", "2013-02", WIKI),
    "ikea":     add_source(conn, "Ispettori cechi e IKEA, ritiro delle polpette", "articolo", "2013-02-25", RFERL),
    "tribunale": add_source(conn, "Tribunale di Parigi, sentenza", "sentenza", SENTENZA, QC),
    "dgccrf":   add_source(conn, "DGCCRF, «Pur bœuf au goût cheval»", "rapporto", None, DGCCRF),
    "wiki":     add_source(conn, "Wikipedia, «2013 horse meat scandal»", "enciclopedia", None, WIKI),
}

# --- Entità, con i nomi alternativi che compaiono nelle fonti ---
ent = {label: add_entity(conn, label, type, aliases) for label, type, aliases in [
    ("FSAI", "istituzione", ["Food Safety Authority of Ireland", "Autorità irlandese per la sicurezza alimentare"]),
    ("Governo irlandese", "istituzione", []),
    ("Governo francese", "istituzione", []),
    ("Governo rumeno", "istituzione", []),
    ("Ispettorato veterinario polacco", "istituzione", []),
    ("Ispettori alimentari cechi", "istituzione", []),
    ("Tribunale di Parigi", "istituzione", ["Tribunal de grande instance de Paris"]),
    ("DGCCRF", "istituzione", ["Direzione generale per la concorrenza, il consumo e la repressione delle frodi"]),
    ("Simon Coveney", "persona", []),
    ("Benoît Hamon", "persona", []),
    ("Jaroslaw Naze", "persona", []),
    ("Erick Lehagre", "persona", []),
    ("Jacques Poujol", "persona", []),
    ("Johannes Fasen", "persona", ["Jan Fasen", "Johannès Fasen"]),
    ("Hendricus Windmeijer", "persona", []),
    ("Tesco", "azienda", []),
    ("Silvercrest", "azienda", ["Silvercrest Foods"]),
    ("ABP Food Group", "azienda", ["ABP"]),
    ("Findus", "azienda", []),
    ("Comigel", "azienda", []),
    ("Tavola", "azienda", []),
    ("Spanghero", "azienda", []),
    ("Draap Trading", "azienda", ["Draap"]),
    ("IKEA", "azienda", []),
    ("Hamburger di manzo Tesco", "prodotto", []),
    ("Lasagne di manzo Findus", "prodotto", []),
    ("Polpette IKEA", "prodotto", ["Köttbullar"]),
    ("Carne equina negli hamburger", "materia prima", []),
    ("Carne equina nelle lasagne", "materia prima", []),
    ("Polonia", "paese", []),
    ("Romania", "paese", []),
    ("Canada", "paese", []),
    ("Svezia", "paese", []),
]}


# --- Chi parla in ciascuna fonte (gli articoli di riepilogo non hanno una voce) ---
for source, voices in {
    "fsai": ["FSAI"],
    "coveney": ["Simon Coveney"],
    "naze": ["Jaroslaw Naze"],
    "findus": ["Findus"],
    "lehagre": ["Erick Lehagre"],
    "hamon11": ["Benoît Hamon"],
    "hamon14": ["Governo francese"],
    "spangh": ["Spanghero"],
    "romania": ["Governo rumeno"],
    "ikea": ["Ispettori alimentari cechi", "IKEA"],
    "tribunale": ["Tribunale di Parigi"],
    "dgccrf": ["DGCCRF"],
}.items():
    for voice in voices:
        add_speaker(conn, src[source], ent[voice])


def A(subject, relation, obj, source, **kw):
    return add_assertion(conn, ent[subject], relation, ent[obj], src[source], **kw)


def ABOUT(subject, relation, target, source, **kw):
    """Affermazione su un'altra affermazione (target = id dell'asserzione)."""
    return add_assertion_about(conn, ent[subject], relation, target, src[source], **kw)


# --- Chi è chi (fonte di riepilogo: known_from = quando il legame era noto) ---
A("Silvercrest", "parte di", "ABP Food Group", "wiki", claim_type="documentato", status="certa",
  known_from="2013-01-16", excerpt="Silvercrest è una controllata di ABP Food Group.")
A("Tavola", "parte di", "Comigel", "wiki", claim_type="documentato", status="certa",
  known_from="2013-02-08", excerpt="Lo stabilimento coinvolto è Tavola, controllata lussemburghese di Comigel.")
A("Erick Lehagre", "dirige", "Comigel", "lehagre", claim_type="documentato", status="certa",
  excerpt="Erick Lehagre è il presidente di Comigel.")
A("Jacques Poujol", "dirige", "Spanghero", "tribunale", claim_type="documentato", status="certa",
  known_from="2013-02-14", excerpt="Jacques Poujol dirigeva lo stabilimento Spanghero all'epoca dei fatti.")
A("Johannes Fasen", "dirige", "Draap Trading", "wiki", claim_type="documentato", status="certa",
  known_from="2013-02-11",
  excerpt="Fasen, direttore di Draap, era già stato condannato nel 2012 per una frode sulla carne equina del 2007.")
A("Hendricus Windmeijer", "prestanome di", "Johannes Fasen", "tribunale", claim_type="documentato", status="certa",
  excerpt="Il tribunale descrive Windmeijer come prestanome di Fasen.")
A("Simon Coveney", "membro di", "Governo irlandese", "coveney", claim_type="documentato", status="certa",
  excerpt="Simon Coveney è il ministro irlandese dell'Agricoltura.")
A("Benoît Hamon", "membro di", "Governo francese", "hamon11", claim_type="documentato", status="certa",
  excerpt="Benoît Hamon è il ministro francese del Consumo.")
A("Jaroslaw Naze", "membro di", "Ispettorato veterinario polacco", "naze", claim_type="documentato", status="certa",
  excerpt="Naze è vicecapo dell'Ispettorato veterinario generale polacco.")

# --- Filiera 1: gli hamburger irlandesi ---
A("FSAI", "rileva carne equina in", "Hamburger di manzo Tesco", "fsai", claim_type="documentato", status="certa",
  excerpt="Un hamburger prodotto da Silvercrest per Tesco contiene circa il 29% di carne equina rispetto al manzo.")
A("Hamburger di manzo Tesco", "prodotto da", "Silvercrest", "fsai", claim_type="documentato", status="certa",
  excerpt="L'hamburger positivo è prodotto da Silvercrest, in Irlanda.")
A("Hamburger di manzo Tesco", "venduto da", "Tesco", "fsai", claim_type="documentato", status="certa",
  excerpt="Il prodotto è venduto da Tesco.")
A("Hamburger di manzo Tesco", "contiene", "Carne equina negli hamburger", "fsai", claim_type="documentato",
  status="certa", value="29 %", excerpt="Circa 29% di DNA equino rispetto al manzo.")
A("Tesco", "ritira", "Hamburger di manzo Tesco", "fsai", claim_type="documentato", status="certa",
  excerpt="Tesco e gli altri distributori coinvolti ritirano i prodotti.")
polonia = A("Carne equina negli hamburger", "proviene da", "Polonia", "coveney", claim_type="interpretazione",
            excerpt="Per Coveney la materia prima polacca è la fonte del DNA equino, con fino al 20% "
                    "di carne equina rispetto al manzo.")
ABOUT("Jaroslaw Naze", "contesta", polonia, "naze", claim_type="documentato", status="certa",
      excerpt="Naze dice di non avere ancora visto prove che colleghino "
              "la Polonia alla carne equina negli hamburger; sono in corso test in sette stabilimenti.")

# --- Filiera 2: le lasagne Findus ---
A("Findus", "ritira", "Lasagne di manzo Findus", "findus", claim_type="documentato", status="certa",
  known_from="2013-02-08", excerpt="Findus ritira le lasagne e smette di comprare da Comigel.")
A("Lasagne di manzo Findus", "contiene", "Carne equina nelle lasagne", "findus", claim_type="documentato",
  status="certa", value="60-100 %", excerpt="11 campioni su 18 contengono tra il 60% e il 100% di carne equina.")
A("Lasagne di manzo Findus", "venduto da", "Findus", "findus", claim_type="documentato", status="certa",
  excerpt="Lasagne di manzo a marchio Findus.")
A("Lasagne di manzo Findus", "prodotto da", "Tavola", "wiki", claim_type="documentato", status="certa",
  known_from="2013-02-08", excerpt="Le lasagne sono prodotte nello stabilimento Tavola di Capellen, in Lussemburgo.")
sp_com = A("Spanghero", "fornisce", "Comigel", "lehagre", claim_type="documentato",
           excerpt="Lehagre indica Spanghero come fornitore della carne adulterata.")
dr_sp = A("Draap Trading", "fornisce", "Spanghero", "hamon11", claim_type="documentato",
          excerpt="Hamon ricostruisce la catena: Spanghero, un commerciante cipriota, il fornitore olandese Draap.")
romania = A("Carne equina nelle lasagne", "proviene da", "Romania", "hamon14", claim_type="interpretazione",
            excerpt="Secondo il governo francese la carne è partita dalla Romania etichettata come cavallo.")
canada = A("Carne equina nelle lasagne", "proviene da", "Canada", "dgccrf", claim_type="documentato",
           known_from=SENTENZA,
           excerpt="La ricostruzione della DGCCRF: la carne equina veniva soprattutto dal Canada e passava "
                   "per i laboratori di un commerciante olandese, che la faceva figurare come manzo "
                   "rumeno o belga.")
ABOUT("Governo rumeno", "contesta", romania, "romania", claim_type="documentato", status="certa",
      excerpt="Bucarest dichiara che non esistono "
              "contratti tra macelli rumeni e trasformatori francesi, ciprioti o olandesi.")
sp_rel = A("Spanghero", "rietichetta come manzo", "Carne equina nelle lasagne", "hamon14",
           claim_type="interpretazione",
           excerpt="Il governo francese accusa Spanghero di aver venduto consapevolmente carne equina "
                   "etichettata come manzo.")
ABOUT("Spanghero", "contesta", sp_rel, "spangh", claim_type="documentato", status="certa",
      excerpt="Spanghero dice di aver agito in buona fede e che "
              "la carne arrivava etichettata «manzo, origine UE».")
fa_rel = A("Johannes Fasen", "rietichetta come manzo", "Carne equina nelle lasagne", "dgccrf",
           claim_type="interpretazione", known_from=SENTENZA,
           excerpt="Per la DGCCRF è il commerciante olandese a sostituire i bolli sanitari, "
                   "facendo passare il cavallo per manzo.")
A("Governo francese", "sospende la licenza di", "Spanghero", "hamon14", claim_type="documentato",
  status="certa", excerpt="La licenza sanitaria di Spanghero viene sospesa.")

# --- La sentenza ---
for persona, pena in [
    ("Johannes Fasen", "2 anni di carcere, mandato d'arresto e interdizione definitiva dal settore della carne."),
    ("Jacques Poujol", "2 anni, di cui 18 mesi con la condizionale; confisca di 100.000 euro."),
    ("Hendricus Windmeijer", "1 anno con la condizionale."),
]:
    A("Tribunale di Parigi", "condanna", persona, "tribunale", claim_type="documentato", status="certa",
      excerpt=f"Colpevole di frode in commercio (tromperie); cade l'accusa di truffa in banda organizzata. {pena}")

# --- Filiera 3: le polpette IKEA, un caso separato ---
A("Ispettori alimentari cechi", "rileva carne equina in", "Polpette IKEA", "ikea", claim_type="documentato",
  status="certa", excerpt="DNA di cavallo in polpette prodotte in Svezia per IKEA, campionate a Brno.")
A("Polpette IKEA", "proviene da", "Svezia", "ikea", claim_type="documentato", status="certa",
  excerpt="Le polpette sono prodotte in Svezia per IKEA.")
A("IKEA", "ritira", "Polpette IKEA", "ikea", claim_type="documentato", status="certa",
  excerpt="Il lotto viene ritirato in 14 paesi.")

# --- Come cambia lo stato delle conoscenze ---
set_status(conn, sp_com, "certa", "2013-02-14", "Il governo francese conferma la catena di fornitura.")
set_status(conn, dr_sp, "certa", SENTENZA, "La sentenza accerta i rapporti tra Fasen e Spanghero.")

# --- I conflitti tra versioni parallele (le smentite sono già affermazioni sulle affermazioni) ---
add_conflict(conn, romania, canada, "Due origini diverse per la stessa carne.")
add_conflict(conn, sp_rel, fa_rel, "Responsabilità della rietichettatura attribuite in modo diverso; "
                                   "non necessariamente incompatibili: il tribunale condanna entrambi.")

conn.commit()
n = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
print(f"Clone '{CLONE}' creato: {n('entities')} entità, {n('assertions')} asserzioni, "
      f"{n('sources')} fonti, {n('conflicts')} conflitti, {n('status_log')} voci di storia.")
