# 0010 — Jedes Produkt liest seine Zelle auf dem Gitter, das seine Datei beschreibt

Status: angenommen (2026.11.0)

## Kontext {#context}

Bis 2026.10.1 führte die Integration ihre eigene Kopie des DE1200-Gitters des
DWD mit (`RS_WHERE` und fest eingetragene Projektionskonstanten in
`radar/odim.py`), berechnete daraus einmal die Zelle jedes Coordinators und
las diese Zeile und Spalte aus jeder Datei. Jede Datei beschreibt ihr Gitter
aber auch selbst, in ihrer ODIM-Gruppe `/where`. Hätte der DWD das Gitter
verschoben oder seine Größe geändert, hätte jede Installation weiter die alte
Zelle gelesen, dann also den Regen eines anderen Orts, bis eine korrigierte
Version erschienen und installiert gewesen wäre: Die Tests hätten es bemerkt,
die Nutzer nicht.

Am 17. Okt. 2026 ergaben die `/where`-Gruppen der RS-Fixture und von
Live-Dateien von RS, RV, HymecNG, RW und SF, jeweils zu einem Gitter gebaut,
ohne etwas aus unseren Konstanten zu übernehmen, für je 100.000 zufällige
Standorte die Zelle der eingebauten Zellsuche. RW und SF schreiben das Gitter
anders als die RADVOR-Produkte und HymecNG: eine andere Parameterreihenfolge
in `projdef`, die Ecken auf 8 Nachkommastellen gerundet (0,3 mm), `y_0` um
0,4 nm verschieden.

## Entscheidung {#decision}

Jeder Leser findet die Zelle, die den Standort enthält, auf dem Gitter, das
seine Datei beschreibt. `radar/grid.py` liest `/where`: nur nordpolare
stereografische Projektion, tolerant bei der Schreibweise, und alles, was eine
Zelle verschieben könnte, wird abgelehnt. Die Nutzdaten müssen genau dieses
Gitter sein, ihre angegebene Größe ist begrenzt (`MAX_CELLS`), und das Gitter
jeder Beschreibung wird nur einmal gebaut. Das eingebaute Gitter, der `index`
der Coordinators und der Parameter `where=` zum Überschreiben (den kein
Aufrufer übergab) sind entfallen.

Der Konfigurationsablauf hat keine Datei, aus der er ein Gitter lesen könnte;
er prüft daher statt des genauen Gitters ein Rechteck aus Breiten- und
Längengraden um DE1200. Ein Standort im Rechteck, aber außerhalb des Gitters
eines Produkts, wird beim Lesen als solcher gemeldet.

## Alternativen {#alternatives}

- Das eingebaute Gitter behalten und zur Laufzeit mit dem `/where` jeder Datei
  vergleichen: Eine harmlose Änderung der Schreibweise (die von RW weicht schon
  ab) würde jede Installation auf einmal lahmlegen.
- Das eingebaute Gitter behalten, es aus einer `/where`-Beschreibung bauen und
  Live-Dateien nur in den täglichen Tests vergleichen: Eine Gitteränderung
  würde innerhalb eines Tages bemerkt, aber die Nutzer läsen bis zu einer neuen
  Version den falschen Ort.
- Im Konfigurationsablauf eine Datei herunterladen, um den Standort exakt zu
  prüfen: Netzwerkfehler bei der Einrichtung, für eine Prüfung, die ein
  Rechteck gut genug erledigt.

## Folgen {#consequences}

- Einem verschobenen oder in der Größe geänderten Gitter in derselben
  Projektion wird ohne neue Version gefolgt, und die Summen und der
  Trockenzähler bleiben am selben Ort.
- Eine Datei in einer anderen Projektion oder mit einem Parameter, der eine
  Zelle verschieben könnte, wird abgelehnt: Ihre Sensoren werden nicht
  verfügbar, mit „please report it“, statt die Werte eines anderen Orts
  anzuzeigen.
- Eine Gitteränderung des DWD lässt nichts mehr fehlschlagen, was Nutzer
  sehen. Sichtbar wird sie in der täglichen wradlib-Teststufe, die das Gitter
  jeder Datei gegen wradlibs DE1200 prüft.
- Eine Datei, die mit falschen `/where`-Attributen veröffentlicht wird, würde
  für diese Veröffentlichung falsch gelesen; dieselbe Teststufe würde es
  zeigen.
