# Reddit Ideen-Validator

Prüft eine Geschäftsidee anhand von Reddit-Diskussionen: Gibt es **Nachfrage** (Leute suchen eine Lösung,
haben Schmerzen, basteln Workarounds, würden zahlen) und gibt es **Konkurrenz** (welche Tools werden genannt,
empfohlen oder kritisiert)?

Baut auf [`reddit-universal-scraper`](reddit-universal-scraper/) auf:
- offizieller OAuth-Client des Repos → Quelle `reddit` (nur mit freigegebenen Reddit-API-Zugangsdaten in `reddit-universal-scraper/.env`)
- Importer der Browser-Extension des Repos → `--import export.json`
- SQLite-Datenbank + Dashboard des Repos → `import-db`

Standardquelle ohne Zugangsdaten ist das öffentliche Archiv **Arctic Shift**. Der Dienst wird privat betrieben
und drosselt stark: Der Validator stellt höchstens alle 20 s eine Anfrage und wartet Limits geduldig ab.
Ein Lauf kann darum 30–90 Minuten dauern; alle Antworten landen im Cache, ein abgebrochener Lauf setzt dort fort.

**Schnellere Alternative:** Browser-Extension des Repos (`reddit-universal-scraper/extension`, in Chrome per
„Entpackte Erweiterung laden“). Auf Reddit nach den Suchbegriffen suchen, Threads öffnen, „Start capture“,
als JSON exportieren und mit `--import` einlesen.

## Ablauf

1. Idee als JSON in `ideas/` anlegen (Vorlage: `ideas/beispiel-rechnungstool.json`):
   - `subreddits`: wo die Zielgruppe diskutiert
   - `search_terms`: Suchbegriffe (kurz, 1–2 Wörter; jede Kombination Subreddit × Begriff kostet Anfragen)
   - `relevance_terms`: mindestens einer muss im Text vorkommen, sonst wird der Treffer verworfen
   - `competitors` (+ `competitor_aliases`): bekannte Anbieter
   - `years`, `per_slice` (Treffer pro Jahr und Anfrage), `max_requests`
   - `trend_counts: true` holt echte Monatszählungen (teure Anfragen, oft vom Server abgelehnt)
   - Anfragen = Subreddits × Suchbegriffe × 2 (Posts/Kommentare) × Jahre
2. Ausführen:
   ```
   .venv\Scripts\python.exe validate.py run ideas\meine-idee.json
   .venv\Scripts\python.exe validate.py run ideas\meine-idee.json --import export.json   # + Browser-Export
   .venv\Scripts\python.exe validate.py analyze ideas\meine-idee.json                    # nur neu auswerten
   .venv\Scripts\python.exe validate.py import-db ideas\meine-idee.json                  # ins Scraper-Dashboard
   ```
3. Ergebnis in `runs/<slug>/`: `report.md` (Bericht), `evidence.jsonl` (alle relevanten Belege), `summary.json`.

## Wie bewertet wird

- **Nachfrage-Signal (0–100)**: Autoren insgesamt, Lösungssuche („is there an app…“), Zahlungsbereitschaft
  („I'd pay…“), Schmerz + Workarounds (Excel, manuell), Breite über Subreddits, Trend aus echten Monatszählungen.
- **Konkurrenz-Dichte (0–100)**: Anzahl etablierter Anbieter, Anteil der Beiträge mit Anbieter-Nennung,
  Empfehlungen bestehender Tools. Kritik an Anbietern wird separat als Marktlücken-Hinweis ausgewiesen.

Die Indizes sind Phrasen-Heuristiken. Die eigentliche Einschätzung entsteht durch Lesen der Belege
(und eine ergänzende Web-Recherche nach Konkurrenten).
