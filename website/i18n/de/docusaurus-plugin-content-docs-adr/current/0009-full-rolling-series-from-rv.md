# 0009 — Die vollständige Reihe gleitender Stunden wird aus RV gebildet

Status: angenommen (2026.11.0)

## Kontext {#context}

`full_rolling_series` erweitert das Attribut `forecast_rolling_1h` von
`Peak hourly precipitation next 120 min` um die 12 Stunden, die vor der
Veröffentlichung begannen. Früher speiste RS den Sensor bei eingeschalteter
Option und decodierte dafür alle 25 Member; RS lud daher alle 5 Minuten sein
ganzes Archiv herunter, statt drei Member per Range-Anfrage zu lesen. Gemessen
an den 576 RS-Archiven auf OpenData vom 11. bis 13. Okt. 2026 waren das 4,6 MB
pro Veröffentlichung statt 0,9 MB, etwa 1,3 GB pro Tag (0,66 GB am trockenen
Tag, 2,1 GB am nassen), und es verdoppelte den Datenverkehr einer Installation
von etwa 0,93 auf 2,0 GB pro Tag.

Frühere Live-Prüfungen hatten gezeigt, dass die Vorhersagestunden von RS die
aufaddierten 5-Minuten-Schritte von RV sind. Am 13. und 14. Okt. 2026 stimmte
jeder RS-Member zweier Veröffentlichungen (eine nass, eine mäßig) Zelle für
Zelle auf dem ganzen Gitter mit der Summe der zwölf RV-Schritte seiner Stunde
überein: die RV-Analysen (`_000`) der Veröffentlichungen bis T, dann die
Vorhersage von RV zum Termin T. Das schließt die Member ein, deren Stunde vor
T begann. Ein fehlender Schritt zählt als 0, und RS hat genau dort keine
Daten, wo keiner der zwölf Schritte welche hat.

## Entscheidung {#decision}

RV bildet die ganze Reihe. Es behält die Analyse jeder Veröffentlichung, die
es übernimmt, eine Stunde lang im Arbeitsspeicher und fügt bei eingeschalteter
Option daraus die 12 früheren Fenster hinzu. RS liest seine drei Member immer
per Range-Anfrage. Ein Live-Test (`test_live_rs_is_summed_rv`) prüft die
Identität täglich.

Die 12 Punkte erscheinen nur, wenn alle 11 früheren Analysen bekannt sind.
Fehlende werden nicht abgerufen; nach einem Neustart oder nach einer
Veröffentlichung, die nie übernommen wurde, hat die Reihe daher bis zu eine
Stunde lang nur die 13 zukünftigen Punkte.

## Alternativen {#alternatives}

- Die fehlenden Analysen in einer Hintergrundrunde abrufen, wie es der
  Regenereignis-Tracker tut: eine vollständige Reihe gleich nach einem
  Neustart, für etwa 2 MB und die Sorgfalt bei der Reihenfolge, die eine
  solche Runde braucht. Für ein Attribut, das nicht aufgezeichnet wird, lohnt
  sich das nicht.
- RS für die Reihe behalten und nur die Member `_000`–`_055` (die ersten 12,
  etwa das halbe Archiv) per Range-Anfrage lesen: Das halbiert die Kosten,
  statt sie zu beseitigen.
- RS ganz weglassen und auch `Precipitation last 60 min` aus den Analysen von
  RV bilden, etwa 260 MB pro Tag weniger. Nicht umgesetzt: Es ändert die
  Quelle von Sensoren, die schon in einer Version enthalten sind, und würde sie
  von RV und von einer Stunde Verlauf abhängig machen.

## Folgen {#consequences}

Mit eingeschalteter Option lädt eine Installation dasselbe herunter wie mit
ausgeschalteter, und RS decodiert nicht mehr 25 Member pro Veröffentlichung.
Die Option ändert den Wert, das Fenster und die zukünftigen Punkte des
Maximums nicht mehr: Sie kommen in beiden Fällen von RV. Eine Installation mit
eingeschalteter Option las sie vorher aus RS; in den seltenen Zellen, in denen
RS des DWD und summiertes RV voneinander abweichen (siehe die spätere Messung
unten), kann sich ihr Maximum mit dieser Änderung daher leicht verschieben.
Veröffentlicht der DWD RS nicht mehr als summiertes RV, schlägt der Live-Test
fehl; der erste Punkt der Reihe und `Precipitation last 60 min` würden dann
nicht mehr übereinstimmen.

## Spätere Messung (17. Okt. 2026) {#later-measurement-17-oct-2026}

Die Identität ist nicht bei jeder Veröffentlichung exakt. Zwölf
Veröffentlichungen im Abstand von 4 h vom 15. bis 17. Okt. stimmten bei
Trockenheit in jeder Zelle überein. Am nassen Morgen des 17. Okt. stimmte die
RS-Vorlaufzeit 0 bei 48 aufeinanderfolgenden Veröffentlichungen in 98,2 bis
100 % der nassen Zellen exakt mit summiertem RV überein; höchstens 0,44 %
wichen um mehr als 0,01 mm ab und 0,11 % um mehr als 0,05 mm, die größte
Abweichung betrug 0,54 mm. Ein abweichender Schritt bleibt für die Stunde, die
er abdeckt, in den Summen. Die Vorhersage-Vorlaufzeiten weichen auf dieselbe
Weise ab, nur seltener. RS und RV waren sich nie uneinig darüber, welche
Zellen Daten haben.

Die Entscheidung bleibt bestehen: Die Abweichungen stammen vom DWD selbst,
betreffen ein oder zwei Prozent der nassen Zellen, und das bei einem Attribut,
das nicht aufgezeichnet wird. Der Live-Test prüft die Identität über ihren
Anteil statt exakt (dieselben Zellen haben Daten, und mindestens 90 % der
nassen Zellen stimmen überein). So lassen ihn die Abweichungen des DWD nicht
fehlschlagen, eine systematische Änderung, die die meisten nassen Zellen
abweichen ließe, aber weiterhin schon.
