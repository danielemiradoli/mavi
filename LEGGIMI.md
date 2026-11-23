# MAVI — prototipo

Un clone di prova (la beffa delle false teste di Modigliani, Livorno 1984)
mostrato come grafo nel browser. Ogni collegamento porta con sé la sua fonte,
il suo tipo (documentato, interpretazione, ipotesi, inferenza) e la storia
del suo stato. La barra in alto mostra cosa si sapeva in una certa data.

## Avvio su Windows

Apri il Terminale dentro la cartella `MAVI_PROJECT` ed esegui, una riga alla volta:

    py --version
    py -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
    .venv\Scripts\python verifica.py
    .venv\Scripts\python -m uvicorn app:app

La prima riga deve mostrare Python 3.10 o superiore.
`verifica.py` ricrea i dati di esempio e controlla le regole: deve finire con
"Tutti i controlli superati".
Poi apri nel browser: http://127.0.0.1:8000

Per fermare il server: Ctrl+C nel Terminale.
Dalla seconda volta in poi basta l'ultima riga.
Se avevi già il passo 1 non serve ricreare l'ambiente: basta sostituire i file
ed eseguire di nuovo `verifica.py` (il database viene ricreato da zero).

## Cosa provare

- Porta la barra al 24 luglio 1984 e clicca il collegamento Testa 2 → Modigliani:
  è "da verificare". Spostala al 3 settembre: diventa "smentita" e compaiono
  i tre studenti.
- Clicca un nodo: vedi i nomi alternativi (es. Fosso Reale / Fosso Mediceo).
- Nel clone della carne di cavallo i quadratini neri sono affermazioni su cui altri
  si pronunciano: la smentita rumena punta alla tesi «la carne proviene dalla Romania».
  Cliccali per vedere la tesi e chi la contesta.
- Le linee sottili «sostiene» collegano chi parla nella fonte alle tesi discutibili.
  Clicca un nodo come Vera Durbé o Governo francese: il pannello elenca cosa sostiene.
- Quando selezioni qualcosa il resto del grafo si attenua: restano in evidenza chi sostiene,
  chi contesta e cosa contraddice. Clicca uno spazio vuoto per tornare alla vista completa.

## Cloni

Ogni clone è un archivio su un argomento. Si sceglie dal menu in alto nella pagina del grafo;
l'ultima voce, «＋ Nuovo clone…», ne crea uno nuovo: descrivi il dominio, il modello propone
la scheda (tipi di entità e relazioni), la correggi e crei il clone.

## Da approfondire

Il pannello iniziale del grafo elenca cosa merita attenzione: conflitti aperti, contestazioni senza
esito, affermazioni con una sola fonte, interpretazioni senza voce. Un clic porta all'affermazione.

## Orientamento

«Orientamento» (in alto nel grafo) non risponde al posto tuo: mette in fila ciò che l'archivio contiene
perché tu possa ragionarci. Domande che vale la pena porsi, ciò che è conteso, su cosa le fonti convergono
(non vuol dire che sia vero), gli attori, che cosa manca, da dove viene ciò che sai. Tutto è calcolato con
regole fisse, uguali per ogni tema, e ogni voce porta al punto del grafo da cui nasce.
A destra il tuo quaderno: ipotesi, domande e note, che puoi segnare come confermate o scartate.
Restano separate dalle affermazioni delle fonti.

## Cerca fonti

«Cerca fonti» (in alto nel grafo) cerca su più servizi aperti insieme, oppure legge i tuoi file (PDF, Word
.docx, pagine web salvate, testo). Scegli i testi che ti interessano e mandali alla coda di revisione: MAVI
legge il testo completo, il modello ne estrae le affermazioni e tu decidi cosa entra nel grafo.
MAVI non risponde al posto tuo: ti aiuta a trovare cosa leggere e su cosa ragionare.

Regola: il motore conosce documenti, non servizi. Di ogni testo si registrano allo stesso modo, comunque
arrivi: chi lo ha pubblicato, il genere, la natura (primaria: il documento o la testimonianza diretta;
secondaria: chi la riporta o la analizza; terziaria: chi riassume altre fonti, come un'enciclopedia),
la lingua e, a parte, il canale da cui è arrivato. Il canale non è mai la fonte: due articoli dello stesso
editore trovati da servizi diversi restano una sola fonte. L'ordine dei risultati è quello di ciascun servizio.

Servizi disponibili:
- **Wikipedia** (italiano e inglese) e **GDELT** (notizie da tutto il mondo, ultimi tre mesi circa): senza chiave.
- **Web (Tavily)**: articoli, documenti e siti ufficiali. Chiave gratuita su https://app.tavily.com
  (1000 ricerche al mese, senza carta di credito).
- **OpenAlex**: articoli scientifici (solo il riassunto). Chiave gratuita su https://openalex.org.

Le chiavi vanno in `impostazioni.json`, nella sezione `"fonti"` (vedi `impostazioni.esempio.json`).
I limiti tecnici (caratteri letti per testo, dimensione dei blocchi, attesa quando il modello è saturo) sono
nella sezione `"limiti"`: dipendono dal modello, non da MAVI.

Il pannello iniziale del grafo mostra «Da dove viene ciò che sai»: le fonti contate per editore, natura,
genere, lingua e canale, con un avviso quando dominano un solo editore, una sola lingua o un solo canale,
o quando mancano le fonti primarie.

## Cerca e filtra

Sotto la barra del tempo: scrivi il nome di un'entità (vale anche un nome alternativo) e premi Invio
per andarci; i menu Tipo, Stato e Affermazione lasciano nel grafo solo le affermazioni che
corrispondono. Lo stato è quello valido alla data scelta con la barra. «Azzera» toglie tutto.

## Attenzione ai dati

I file `seed_...py` ricreano il loro clone da zero: rieseguirli cancella ciò che hai approvato
in revisione. `verifica.py` invece mette da parte i database e alla fine li rimette com'erano.

Su Windows, per avviare MAVI basta un doppio clic su `avvia_mavi.bat`: apre il browser da solo,
e il clone si sceglie nella pagina.

## Secondo clone: lo scandalo della carne di cavallo (2013)

    .venv\Scripts\python seed_carne_cavallo.py
    $env:MAVI_CLONE="carne_cavallo"
    .venv\Scripts\python -m uvicorn app:app

La seconda riga vale per PowerShell (il Terminale predefinito di Windows 11);
nel vecchio Prompt dei comandi si scrive `set MAVI_CLONE=carne_cavallo`.
Per tornare a Modigliani chiudi il Terminale, oppure scrivi `$env:MAVI_CLONE="modigliani"`.

## Aggiungere testi: il modello che estrae le affermazioni

Il modello si sceglie in `impostazioni.json`: `"fornitore"` indica quale usare, `"fornitori"`
elenca quelli configurati. Ce ne sono di due tipi:
- **cloud** (es. Groq, gratuito entro certi limiti): veloce e preciso, ma il testo esce dal PC;
- **locale con Ollama** (es. `qwen2.5:7b`, `gemma3:4b`): tutto resta sul PC, ma è lento e meno preciso.

Per Groq: crea una chiave gratuita su https://console.groq.com/keys e incollala tra le virgolette
di `"chiave"`. Non condividere `impostazioni.json`: contiene la chiave.
Per un modello locale: scaricalo con `ollama pull nome-del-modello`.

1. Confronta i modelli sullo stesso testo, senza toccare il database:

       .\.venv\Scripts\python prova_estrazione.py

   (oppure doppio clic su `esegui.bat`, che scrive tutto in `esito.txt`).
   Per ogni modello configurato stampa le proposte, gli avvisi e il tempo impiegato.
2. Avvia MAVI sul clone della carne di cavallo e clicca «Aggiungi un testo · coda di revisione».
   Incolla un testo, compila titolo, data e chi parla, e premi «Estrai le affermazioni».
3. Nella coda correggi le proposte se serve, poi approva o scarta. Nulla entra nel grafo senza
   la tua approvazione, e ciò che approvi entra come «da verificare».

Il modello riconosce anche le smentite: quando nel testo qualcuno contesta un'affermazione, propone
una «presa di posizione» (scheda con il bordo nero) che punta a un'affermazione già nel grafo oppure a una
dello stesso testo. In questo secondo caso approva prima l'affermazione contestata; se la scarti, sparisce
anche la smentita. Per provarlo: `.\.venv\Scripts\python prova_estrazione.py esempi\romania.txt`.

Le quantità (percentuali, pesi, prezzi, numeri di campioni) vanno nel campo «Valore»: si scrivono anche
come «circa il 29 %», «tra il 60 e il 100 %», «0,5 kg». Compaiono sul collegamento; il pannello confronta
i valori della stessa relazione, e «Da approfondire» segnala lo stesso legame con numeri che non si sovrappongono.

Gli avvisi in rosso segnalano un estratto che non compare nel testo (probabile invenzione),
soggetto o oggetto di tipo sbagliato per la relazione, e asserzioni già presenti nel grafo.

## Creare un nuovo clone

1. Crea `clones/<nome>/clone.json` sul modello di quelli esistenti
   (nome, obiettivo, domande guida, tipi di entità, relazioni con definizione).
2. Scrivi i dati come in `seed_modigliani.py` o `seed_carne_cavallo.py`.
3. Avvia con il clone scelto, come sopra.

Il database rifiuta tipi di entità e relazioni non previsti dalla scheda.

## File

- `core/database.py` — schema e funzioni del database (un file SQLite per clone)
- `clones/<nome>/clone.json` — la scheda del dominio
- `seed_modigliani.py` — dati di esempio; rieseguirlo ricrea il database da zero
- `verifica.py` — controlli automatici delle regole (l'estrazione è provata con un modello simulato)
- `core/extraction.py` — estrazione con il modello scelto e coda di revisione
- `prova_estrazione.py` — confronta i modelli configurati senza toccare il database
- `impostazioni.json` — quale modello usa l'estrazione (con le chiavi: non condividerlo)
- `esegui.bat` — su Windows: prepara tutto, esegue i controlli e il confronto, scrive in `esito.txt`
- `avvia_mavi.bat` — su Windows: avvia MAVI sul clone scelto e apre il browser
- `esempi/nestle.txt` — testo di prova
- `gui/revisione.html` — la pagina per aggiungere testi e revisionare le proposte
- `app.py` — server locale
- `gui/index.html` — la pagina con il grafo (`cytoscape.min.js` è la libreria grafica, inclusa per funzionare offline)
