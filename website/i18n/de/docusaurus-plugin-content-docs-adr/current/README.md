# Architekturentscheidungen

Warum die Integration so ist, wie sie ist, und wie sie vorher war. CLAUDE.md
nennt die Regeln, die daraus folgen; ein Eintrag bewahrt die Begründung, die
Zahlen, auf denen sie beruhte, und die verworfenen Alternativen, damit eine
spätere Änderung sie abwägen kann, statt sie neu zu entdecken.

Ein Eintrag wird nach seiner Annahme nicht mehr geändert, außer um ihn als
durch einen neueren abgelöst zu kennzeichnen. Versionen werden mit ihrer
Versionsnummer bezeichnet (`2026.11.0`).

| # | Entscheidung | Seit |
|---|--------------|------|
| [0001](0001-entity-names-state-their-window.md) | Entitätsnamen nennen ihr Zeitfenster; eine ausgelieferte ID wird nie wiederverwendet | 2026.11.0 |
| [0002](0002-rw-reads-the-clock-hour.md) | RW liest den Lauf, der zur vollen Stunde endet, nicht HH:50 | 2026.11.0 |
| [0003](0003-rw-10-minute-runs-only-for-the-dry-streak.md) | Die 10-Minuten-Läufe von RW speisen den Trockenzähler, sonst nichts | 2026.11.0 |
| [0004](0004-radolan-hdf5-edition.md) | RW und SF werden in ihrer HDF5-Ausgabe gelesen | 2026.10.1 |
| [0005](0005-running-totals.md) | Laufende Summen zählen je Veröffentlichung, und RW speist die Hauptsumme | 2026.11.0 |
| [0006](0006-rain-events-opt-in-entity.md) | Regenereignisse sind eine eigene, optionale Entität, die bei jeder Veröffentlichung neu berechnet wird | 2026.11.0 |
| [0007](0007-staleness-deadline-on-the-overdue-release.md) | Ob Daten veraltet sind, entscheidet eine Frist ab der überfälligen Veröffentlichung | 2026.9.0 |
| [0008](0008-grid-lookup-floors-from-the-outer-corner.md) | Die Zellsuche rundet vom äußeren Eckpunkt aus ab | 2026.10.0 |
| [0009](0009-full-rolling-series-from-rv.md) | Die vollständige Reihe gleitender Stunden wird aus RV gebildet, nicht aus RS | 2026.11.0 |
| [0010](0010-cells-on-the-grid-each-file-describes.md) | Jedes Produkt liest seine Zelle auf dem Gitter, das seine Datei beschreibt | 2026.11.0 |
| [0011](0011-dry-streak-gaps-checked-against-rw.md) | Lücken in der Quelle des Trockenzählers werden an den Stunden von RW geprüft | 2026.11.0 |
