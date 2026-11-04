# 0004 — RW und SF werden in ihrer HDF5-Ausgabe gelesen

Status: angenommen (2026.10.1)

## Kontext {#context}

Bis 2026.10.0 wurden RW und SF in der alten Binärausgabe des DWD gelesen
(.bz2, ein nationales 900x900-Gitter auf der Kugel), mit einem aus wradlib
übernommenen Leser (`radar/radolan.py`, `radar/georef.py`). Der DWD hatte
angekündigt, die Binärausgabe abzuschalten; dieselben Analysen erscheinen in
einer HDF5-Ausgabe (`raa01-<p>_10000-<yymmddHHMM>-dwd---bin.hdf5`), als
ODIM_H5 auf dem DE1200-Gitter, das RS, RV und HymecNG bereits nutzen.

## Entscheidung {#decision}

RW und SF werden in der HDF5-Ausgabe gelesen, über dasselbe
`read_odim_composite_cell` und dieselbe Zellsuche wie die RADVOR-Produkte. Der
Binärleser wurde samt seinen Tests und Fixtures entfernt; die Git-Historie hat
sie, falls die Binärausgabe je wieder gebraucht wird.

## Folgen {#consequences}

Die beiden Ausgaben sind dieselbe Analyse auf verschiedenen Gittern, keine
zellgenaue Kopie. Geprüft an Live-Dateien (2026-10-12): Flächenmittel über
~1100 Orte stimmen auf 1 % überein (SF 0,717 gegenüber 0,725 mm), während der
eigene Wert eines Orts in ~65–80 % der nassen Fälle abweicht (Median 0,1 mm,
bei scharfen Gradienten bis zu einigen mm) und nur in ~60 % der Fälle in der
3x3-Nachbarschaft der alten Zelle zu finden ist. Nutzer sehen beim Wechsel
kleine Wertänderungen; sonst ändert sich nichts.

Zeitverhalten: Die HDF5-Datei von RW erscheint ~25,7 min nach dem Ende ihres
Fensters, wie die binäre; die von SF nach ~29,3 min, ~2,5 min später als ihre
binäre, daher beträgt der `RELEASE_DELAY` von SF 31 min.
