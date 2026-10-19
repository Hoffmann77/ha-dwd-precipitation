---
title: RADVOR-RS-Nowcast
description: Niederschlag letzte 60 min, nächste 60 min, nächste 60–120 min und nächste 120 min.
---

RADVOR RS ist der Radar-Nowcast (Kurzfristvorhersage) des DWD für
Stundensummen. Alle 5 Minuten veröffentlicht der DWD einen Satz gleitender
60-Minuten-Summen: die Stunde, die gerade gemessen wurde, und Vorhersagen für
die kommenden Stunden. Die Integration liest drei davon und stellt vier
Sensoren bereit.

Alle vier sind Summen in Millimetern, keine Raten. Wie stark es regnet, zeigt
[Niederschlagsintensität aktuell](radvor-rv.md#precipitation-intensity-now).

## Sensoren {#sensors}

| Sensor | Einheit | Fenster, für eine Veröffentlichung zum Termin 14:00 |
|--------|---------|-----------------------------------------------------|
| **Niederschlag letzte 60 min** | mm | 13:00–14:00, gemessen |
| **Niederschlag nächste 60 min** | mm | 14:00–15:00, Vorhersage |
| **Niederschlag nächste 60–120 min** | mm | 15:00–16:00, Vorhersage |
| **Niederschlag nächste 120 min** | mm | 14:00–16:00, Vorhersage |

Die Fenster zählen ab dem Termin der DWD-Veröffentlichung, einem Vielfachen
von 5 Minuten. Die Veröffentlichung zum Termin 14:00 erreicht Home Assistant
gegen 14:04 bis 14:05, „nächste 60 min“ deckt dann also ungefähr die nächsten
55 Minuten ab.

### Niederschlag letzte 60 min {#precipitation-last-60-min}

Der Regen, der in den vergangenen 60 Minuten gefallen ist, nur aus Radardaten,
alle 5 Minuten aktualisiert. Weil die Stunde in 5-Minuten-Schritten
weiterrückt, bleibt ein kurzer Schauer noch eine volle Stunde lang darin,
nachdem er vorbeigezogen ist.

Die angeeichte Summe einer vollen Stunde liefert
[Niederschlag vorige Stunde](radolan.md); sie kommt später, ist aber genauer.

### Niederschlag nächste 60 min {#precipitation-next-60-min}

Die vorhergesagte Summe für die nächste Stunde.

### Niederschlag nächste 60–120 min {#precipitation-next-60120-min}

Die vorhergesagte Summe für die zweite Stunde voraus.

### Niederschlag nächste 120 min {#precipitation-next-120-min}

Die vorhergesagte Summe für die ganzen nächsten zwei Stunden: genau
`Niederschlag nächste 60 min` plus `Niederschlag nächste 60–120 min`, du musst
die beiden also nicht in einem Template addieren. Der Sensor ist `unknown`
(„Unbekannt“), wenn einer der beiden es ist, denn eine halbe Vorhersage ist
keine Zwei-Stunden-Summe.

## Verwandte Sensoren {#related-sensors}

- [Maximaler Stundenniederschlag nächste 120 min](radvor-rv.md#peak-hourly-precipitation)
  findet die nasseste Stunde *irgendwo* in den nächsten zwei Stunden. Ein
  Wolkenbruch, der über die Ein-Stunden-Marke reicht, zeigt sich dort
  vollständig, während `Niederschlag nächste 60 min` und `nächste 60–120 min`
  jeweils nur einen Teil davon sehen.
- [Zeitraum ohne Niederschlag](dry-streak.md) kann
  `Niederschlag letzte 60 min` als Quelle verwenden.

## Gut zu wissen {#good-to-know}

- **Nur Radar.** RS ist nicht mit Niederschlagsmessern angeeicht. Es kann
  daher von einem Messgerät am Boden abweichen, und auch von den
  [RADOLAN](radolan.md)-Sensoren.
- **Keine Daten:** Ein Sensor ist `unknown`, wenn die Datei des DWD keinen
  Wert für deinen Standort hat, zum Beispiel während ein Radar in der Nähe
  außer Betrieb ist. Das Protokoll meldet das einmal, und noch einmal, wenn
  wieder Daten da sind.
- **Datenmenge:** Der DWD veröffentlicht alle 25 gleitenden Stunden in einem
  Archiv von bis zu etwa 17,5 MB. Die Integration lädt nur die drei Stunden
  herunter, die sie braucht, etwa ein Fünftel der Datei.
