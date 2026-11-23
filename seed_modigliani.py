"""Dati di esempio: la beffa delle false teste di Modigliani (Livorno, 1984).

Ricrea da zero il database del clone "modigliani".
Note:
- il campo `excerpt` contiene brevi sintesi scritte a mano, non citazioni
  letterali (tranne la frase di Argan);
- l'intervista a Panorama è datata 3 settembre 1984: è il lunedì dopo la
  presentazione di domenica 2 settembre, come risulta incrociando le due fonti.
"""

from core.database import (add_assertion, add_conflict, add_entity, add_source,
                           add_speaker, connect, db_path, set_status)

CLONE = "modigliani"
IFQ = ("https://www.ilfattoquotidiano.it/2017/01/24/modigliani-32-anni-fa-la-burla-"
       "delle-teste-false-che-fece-arrossire-il-mondo-dellarte/2957324/")
M1909 = "https://www.modigliani1909.com/la_beffa_del_1984.html"
PANORAMA = "1984-09-03"
FROGLIA = "1984-09-13"

db_path(CLONE).unlink(missing_ok=True)
conn = connect(CLONE)

# --- Fonti: chi afferma che cosa (url = dove l'affermazione è documentata) ---
src = {
    "durbe":     add_source(conn, "Vera e Dario Durbé, attribuzione delle teste", "dichiarazione", "1984-07-24", IFQ),
    "argan":     add_source(conn, "Giulio Carlo Argan, dichiarazione", "dichiarazione", "1984-07", IFQ),
    "pepi":      add_source(conn, "Carlo Pepi, dichiarazioni", "dichiarazione", "1984-07", M1909),
    "panorama":  add_source(conn, "Intervista dei tre studenti a Panorama", "intervista", PANORAMA, IFQ),
    "froglia":   add_source(conn, "Angelo Froglia, ammissione", "dichiarazione", FROGLIA, IFQ),
    "catalogo":  add_source(conn, "Catalogo «Due pietre ritrovate di Amedeo Modigliani»", "catalogo", "1984-08", M1909),
    "razzaguta": add_source(conn, "G. Razzaguta, testimonianza", "testimonianza", None, M1909),
    "ifq":       add_source(conn, "Il Fatto Quotidiano, ricostruzione della vicenda", "articolo", "2017-01-24", IFQ),
    "m1909":     add_source(conn, "modigliani1909.com, «La beffa del 1984»", "sito web", None, M1909),
}

# --- Entità, con i nomi alternativi che compaiono nelle fonti ---
ent = {label: add_entity(conn, label, type, aliases) for label, type, aliases in [
    ("Amedeo Modigliani", "persona", ["Modì", "Modigliani"]),
    ("Vera Durbé", "persona", ["Vera Durbè"]),
    ("Dario Durbé", "persona", ["Dario Durbè"]),
    ("Giulio Carlo Argan", "persona", []),
    ("Carlo Pepi", "persona", []),
    ("Pietro Luridiana", "persona", []),
    ("Michele Ghelarducci", "persona", []),
    ("Pierfrancesco Ferrucci", "persona", ["Pier Francesco Ferrucci"]),
    ("Angelo Froglia", "persona", []),
    ("Testa 1", "opera", []),
    ("Testa 2", "opera", []),
    ("Testa 3", "opera", []),
    ("Fosso Reale", "luogo", ["Fosso Mediceo"]),
    ("Mostra di Villa Maria", "evento", []),
    ("Dragaggio del Fosso Reale", "evento", []),
    ("Comune di Livorno", "organizzazione", []),
]}


# --- Chi parla in ciascuna fonte ---
for source, voices in {
    "durbe": ["Vera Durbé", "Dario Durbé"],
    "argan": ["Giulio Carlo Argan"],
    "pepi": ["Carlo Pepi"],
    "panorama": ["Pietro Luridiana", "Michele Ghelarducci", "Pierfrancesco Ferrucci"],
    "froglia": ["Angelo Froglia"],
}.items():
    for voice in voices:
        add_speaker(conn, src[source], ent[voice])


def A(subject, relation, obj, source, **kw):
    return add_assertion(conn, ent[subject], relation, ent[obj], src[source], **kw)


# --- Il contesto (fonti retrospettive: known_from indica quando il fatto era noto) ---
A("Vera Durbé", "cura", "Mostra di Villa Maria", "m1909", claim_type="documentato", status="certa",
  valid_from="1984", known_from="1984-07",
  excerpt="La mostra per il centenario è affidata a Vera Durbé, conservatrice del museo.")
A("Dario Durbé", "cura", "Mostra di Villa Maria", "ifq", claim_type="documentato", status="certa",
  valid_from="1984", known_from="1984-07",
  excerpt="Curatori dell'esposizione sono i fratelli Dario e Vera Durbé.")
A("Mostra di Villa Maria", "dedicata a", "Amedeo Modigliani", "m1909", claim_type="documentato", status="certa",
  valid_from="1984", known_from="1984-07",
  excerpt="La mostra celebra il centenario della nascita di Modigliani.")
A("Vera Durbé", "promuove", "Dragaggio del Fosso Reale", "ifq", claim_type="documentato", status="certa",
  valid_from="1984-07", known_from="1984-07",
  excerpt="Vera Durbé ottiene dal Comune le autorizzazioni per cercare le sculture nel fosso.")
A("Comune di Livorno", "finanzia", "Dragaggio del Fosso Reale", "m1909", claim_type="documentato", status="certa",
  valid_from="1984-07-14", known_from="1984-07-14",
  excerpt="Il Comune finanzia le ricerche nel fosso; il dragaggio inizia sabato 14 luglio.")
A("Dragaggio del Fosso Reale", "avviene in", "Fosso Reale", "ifq", claim_type="documentato", status="certa",
  valid_from="1984-07-14", known_from="1984-07-14",
  excerpt="Le operazioni di dragaggio si svolgono nel Fosso Reale, davanti ai livornesi.")

# --- La leggenda: stessa storia, due date ---
leg_1909 = A("Amedeo Modigliani", "getta sculture in", "Fosso Reale", "catalogo", claim_type="ipotesi",
             valid_from="1909",
             excerpt="Secondo il catalogo, Modigliani avrebbe gettato le teste nel fosso nel 1909.")
leg_1916 = A("Amedeo Modigliani", "getta sculture in", "Fosso Reale", "razzaguta", claim_type="ipotesi",
             valid_from="1916",
             excerpt="Razzaguta colloca l'episodio sette anni più tardi.")

# --- I ritrovamenti ---
A("Testa 1", "ritrovata in", "Fosso Reale", "ifq", claim_type="documentato", status="certa",
  valid_from="1984-07-24", known_from="1984-07-24",
  excerpt="La mattina del 24 luglio il fosso restituisce una prima testa scolpita.")
A("Testa 2", "ritrovata in", "Fosso Reale", "ifq", claim_type="documentato", status="certa",
  valid_from="1984-07-24", known_from="1984-07-24",
  excerpt="Nel pomeriggio dello stesso giorno emerge una seconda testa.")
A("Testa 3", "ritrovata in", "Fosso Reale", "ifq", claim_type="documentato", status="certa",
  valid_from="1984-08-10", known_from="1984-08-10",
  excerpt="Il 10 agosto la draga recupera una terza testa.")

# --- Le attribuzioni a Modigliani: interpretazioni, poi smentite ---
t1_mod = A("Testa 1", "è opera di", "Amedeo Modigliani", "durbe", claim_type="interpretazione",
           excerpt="Per i fratelli Durbé non ci sono dubbi: le teste sono di Modigliani.")
t2_mod = A("Testa 2", "è opera di", "Amedeo Modigliani", "durbe", claim_type="interpretazione",
           excerpt="Per i fratelli Durbé non ci sono dubbi: le teste sono di Modigliani.")
t3_mod = A("Testa 3", "è opera di", "Amedeo Modigliani", "durbe", claim_type="interpretazione",
           known_from="1984-08-10",
           excerpt="Anche la terza testa viene esposta in mostra come opera di Modigliani.")
t2_argan = A("Testa 2", "è opera di", "Amedeo Modigliani", "argan", claim_type="interpretazione",
             excerpt="«Le teste sono certamente autentiche».")

# --- Lo scettico ---
for testa, known in (("Testa 1", "1984-07"), ("Testa 2", "1984-07"), ("Testa 3", "1984-08-10")):
    A("Carlo Pepi", "giudica falsa", testa, "pepi", claim_type="interpretazione",
      valid_from="1984", known_from=known,
      excerpt="Pepi sostiene che le tre sculture sono false e scolpite da due mani diverse.")

# --- Le confessioni ---
t2_stud = [
    A("Testa 2", "è opera di", studente, "panorama", claim_type="documentato", status="certa",
      valid_from="1984-07",
      excerpt="I tre studenti dichiarano di aver scolpito la seconda testa con un trapano elettrico, "
              "e pubblicano le foto scattate mentre la realizzavano.")
    for studente in ("Pietro Luridiana", "Michele Ghelarducci", "Pierfrancesco Ferrucci")
]
t1_frog = A("Testa 1", "è opera di", "Angelo Froglia", "froglia", claim_type="documentato", status="certa",
            valid_from="1984", excerpt="Froglia ammette di essere l'autore delle altre due teste.")
t3_frog = A("Testa 3", "è opera di", "Angelo Froglia", "froglia", claim_type="documentato", status="certa",
            valid_from="1984", excerpt="Froglia ammette di essere l'autore delle altre due teste.")

# --- Un'inferenza, aggiunta a mano: segue dalla confessione di Froglia ---
A("Testa 1", "stessa mano di", "Testa 3", "froglia", claim_type="inferenza", status="certa", is_manual=1,
  excerpt="Se Froglia ha scolpito entrambe, le due teste sono della stessa mano. "
          "Conferma a posteriori il giudizio di Pepi sulle «due mani diverse».")

# --- Come cambia lo stato delle conoscenze ---
set_status(conn, t2_mod, "smentita", PANORAMA, "Gli studenti rivendicano la Testa 2 su Panorama, con foto.")
set_status(conn, t2_argan, "smentita", PANORAMA, "Gli studenti rivendicano la Testa 2 su Panorama, con foto.")
set_status(conn, t1_mod, "smentita", FROGLIA, "Angelo Froglia si dichiara autore della Testa 1.")
set_status(conn, t3_mod, "smentita", FROGLIA, "Angelo Froglia si dichiara autore della Testa 3.")

# --- I conflitti, dichiarati a mano ---
add_conflict(conn, leg_1909, leg_1916, "Stesso episodio, due date incompatibili.")
add_conflict(conn, t1_mod, t1_frog, "Paternità incompatibili della Testa 1.")
add_conflict(conn, t3_mod, t3_frog, "Paternità incompatibili della Testa 3.")
add_conflict(conn, t2_mod, t2_stud[0], "Paternità incompatibili della Testa 2.")
add_conflict(conn, t2_argan, t2_stud[0], "Paternità incompatibili della Testa 2.")

conn.commit()
n = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
print(f"Clone '{CLONE}' creato: {n('entities')} entità, {n('assertions')} asserzioni, "
      f"{n('sources')} fonti, {n('conflicts')} conflitti, {n('status_log')} voci di storia.")
