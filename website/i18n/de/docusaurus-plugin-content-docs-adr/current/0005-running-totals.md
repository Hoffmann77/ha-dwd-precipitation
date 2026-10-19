# 0005 — Laufende Summen zählen je Veröffentlichung, und RW speist die Hauptsumme

Status: angenommen (2026.11.0)

## Kontext {#context}

2026.10.0 lieferte zwei `TOTAL_INCREASING`-Sensoren aus, `Precipitation total
(hourly)` aus RW und `Precipitation total (daily)` aus `sf_2350`. Die
Statistiken von HA sehen jede Stunde eine Stunde zu spät (11:00–12:00 wird um
~12:28 addiert). Bei der Summe aus RW rutscht deshalb nur die letzte Stunde
eines Tages in den nächsten, während bei der täglichen Summe der Regen jedes
Tages in den Statistiken des *nächsten* Tages landet.

## Entscheidung {#decision}

- Eine Summe richtet sich nach dem Zeitstempel der Veröffentlichung, nie danach,
  ob sich der Wert ändert: Zwei gleich nasse Stunden sind zwei
  Veröffentlichungen, und eine doppelt gesehene Veröffentlichung wird einmal
  gezählt.
- RW speist `Precipitation total`, die Summe, die man verwenden sollte
  (umbenannt von `(hourly)`, sodass neue Installationen `precipitation_total`
  bekommen; siehe [0001](0001-entity-names-state-their-window.md)).
- `Precipitation total daily` behält seine ID, ist aber standardmäßig
  deaktiviert (`entity_registry_enabled_default=False`). Ihn zu entfernen würde
  die Entitäten der Nutzer verwaisen lassen. Die Vorgabe gilt nur, wenn HA eine
  Entität zum ersten Mal registriert; Installationen, die ihn hatten, behalten
  ihn also aktiviert. Das Aktivieren lädt den Eintrag neu, und er beginnt bei 0,
  wie jede neue Summe.
- Verpasste Veröffentlichungen kommen auf eine `pending`-Liste, die mit der
  Summe gespeichert wird, und werden erst entfernt, wenn sie addiert sind; so
  verliert weder ein Neustart noch ein fehlgeschlagener Abruf eine davon.

## Verworfene Alternativen {#alternatives-turned-down}

- **Eine Summe mit einer Option für die Quelle.** Ein Wechsel der Quelle ließe
  einen `TOTAL_INCREASING`-Sensor springen.
- **Die tägliche Summe entfernen.** Siehe oben; es kostet Nutzer ihre Entität.
