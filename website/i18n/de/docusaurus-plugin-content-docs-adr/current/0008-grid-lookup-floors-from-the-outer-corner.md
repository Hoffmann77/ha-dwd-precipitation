# 0008 — Die Zellsuche im Gitter rundet ab der äußeren Ecke ab

Status: angenommen (2026.10.0)

## Kontext {#context}

Die ODIM-Attribute `LL_*`/`UL_*`/`UR_*`/`LR_*` sind die äußeren Ecken der
Randpixel, keine Pixelmitten. Beide Zellsuchen, die die Integration hatte (die
für DE1200 bei RADVOR, die nationale für die RADOLAN-Binärausgabe),
behandelten sie als Mitten. Das verschiebt die Suche um eine halbe Zelle und
wählt für etwa 3 von 4 Standorten eine Nachbarzelle. Beide waren bis 2026.10.0
auf diese Weise falsch.

## Entscheidung {#decision}

Den Standort projizieren, dann seinen Abstand von der äußeren unteren linken
Ecke des Gitters abrunden (floor). Nie zur nächsten ganzen Zahl runden, und
nie die nächstgelegene Gitterkoordinate nehmen.

Die Referenz-Teststufe prüft das Ergebnis gegen wradlibs eigenes Gitter
(`mode="edge"`) statt gegen eine Nachimplementierung unserer Arithmetik, die
denselben Fehler wiederholen könnte, und legt wradlibs Gitter auf die
Eckattribute der Fixture-Datei fest.

## Folgen {#consequences}

Seit RW und SF auf die HDF5-Ausgabe umgestiegen sind
([0004](0004-radolan-hdf5-edition.md)), gibt es nur noch die Zellsuche für
DE1200.
