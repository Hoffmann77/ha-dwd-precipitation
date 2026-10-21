# 0002 — RW liest den Lauf, der zur vollen Stunde endet, nicht HH:50

Status: angenommen (2026.11.0)

## Kontext {#context}

Der DWD rechnet RW alle 10 Minuten, jeder Lauf die Stunde, die zu dieser :x0
endet. Bis 2026.10.1 las die Integration den Lauf um HH:50. Warum, war nirgends
festgehalten; es ist die traditionelle Stunde von RADOLAN, und SF wird weiterhin
nur um :50 veröffentlicht (OpenData hat keine andere SF-Minute).

Nur eine volle Stunde kann „previous hour“ heißen (siehe
[0001](0001-entity-names-state-their-window.md)) und zu den stündlichen
Statistiken von HA passen. Die Frage war, ob der Lauf um :00 so gut ist wie
der um :50.

`scripts/compare_rw_runs.py` vergleicht jeden RW-Lauf auf OpenData (48 h)
Zelle für Zelle mit dem reinen Radarwert RS `_000` für dieselbe Stunde. Würden
die Läufe innerhalb der Stunde weniger Niederschlagsmesser verwenden, lägen sie
näher an RS. Das tun sie nicht: Über 285 nasse Läufe (2026-10-10..12) weicht
jede Laufminute gleich stark von RS ab (mittleres |RW-RS| 0,53–0,58 mm,
58–62 % relativ, 76–78 % der nassen Zellen angeeicht). Jede Laufminute wird
nach ~25,7 min veröffentlicht (288 Läufe, 2026-10-13).

## Entscheidung {#decision}

`rw` liest den Lauf, der zur vollen Stunde endet. SF bleibt bei :50, die
Fenster von `rw` und `sf` liegen also jetzt 10 Minuten auseinander.

Eine vor 2026.11.0 gespeicherte Summe hat ein `last_release` um :50, außerhalb
des neuen Terminrasters. Beim Wiederherstellen bildet `counted_on_grid()` es
einmalig auf die :00-Veröffentlichung vor dem ersten Fenster ab, das danach
beginnt, sodass das Zählen dort weitergeht: Die 10 Minuten dazwischen fallen
einmal weg, statt dass 50 doppelt gezählt werden (`counted_until` liegt bis zur
nächsten Veröffentlichung 10 Minuten voraus).

## Folgen {#consequences}

Führe `scripts/compare_rw_runs.py` erneut aus, bevor du dich für etwas Neues
auf den Qualitätsvergleich verlässt; der DWD kann ändern, wie die Läufe
angeeicht werden.
