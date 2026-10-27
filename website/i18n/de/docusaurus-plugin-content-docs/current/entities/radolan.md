---
title: RADOLAN RW und SF
description: Niederschlag vorige Stunde, letzte 24h und gestern, aus den mit Bodenmessungen angeeichten Radaranalysen des DWD.
---

RADOLAN ist die Radaranalyse des DWD, korrigiert mit den Messungen seines
Netzes von Niederschlagsmessern. Sie ist langsamer als der Radar-Nowcast
(Kurzfristvorhersage), liegt aber näher an dem, was ein Niederschlagsmesser
am Boden misst. Die Integration liest zwei RADOLAN-Produkte:

- **RW**, eine Stunde Niederschlag, stündlich veröffentlicht (und alle
  10 Minuten neu berechnet).
- **SF**, 24 Stunden Niederschlag, stündlich zur Minute :50 veröffentlicht.

## Sensoren {#sensors}

| Sensor | Einheit | Zeitfenster | Verfügbar |
|--------|---------|-------------|-----------|
| **Niederschlag vorige Stunde** | mm | die letzte volle Stunde, z. B. 11:00–12:00 | etwa 30 Minuten nach Ende der Stunde (12:28) |
| **Niederschlag letzte 24h** | mm | die 24 Stunden bis zur letzten Minute :50 | etwa 30 Minuten nach :50 |
| **Niederschlag gestern** | mm | der vorige Kalendertag, deutsche Ortszeit | einmal täglich, gegen 00:20 |

### Niederschlag vorige Stunde {#precipitation-previous-hour}

Regen, der in der letzten vollen Stunde gefallen ist, korrigiert mit den Daten
der Niederschlagsmesser. Der Sensor aktualisiert sich stündlich, etwa
30 Minuten nach Ende der Stunde: die Stunde 11:00–12:00 kommt gegen 12:30.
Damit ist er langsamer als [Niederschlag letzte 60 min](radvor-rs.md), aber
genauer.

Es ist eine volle Stunde, weil sie dann zu den stündlichen Statistiken von
Home Assistant passt und zu dem, was „die vorige Stunde“ in einer Automation
bedeutet. Der DWD berechnet seine Analyse außerdem alle 10 Minuten neu, jeweils
für die Stunde, die dann endet; die Integration nutzt diese Läufe nur für
[Zeitraum ohne Niederschlag](dry-streak.md), wo sie ein Zurücksetzen bis zu
einer Stunde früher sichtbar machen.

### Niederschlag letzte 24h {#precipitation-last-24h}

Regen der vergangenen 24 Stunden, stündlich aktualisiert. Der DWD
veröffentlicht diese Analyse nur für Zeitfenster, die zur Minute :50 enden,
daher endet ihr Zeitfenster 10 Minuten vor dem von
`Niederschlag vorige Stunde`.

### Niederschlag gestern {#precipitation-yesterday}

Die Summe des vorigen Kalendertags, deutsche Ortszeit (die 24 Stunden bis
23:50). Der Sensor aktualisiert sich einmal täglich, gegen 00:20.

## Keine Daten für deinen Standort {#no-data-for-your-location}

Alle drei sind `unknown` („Unbekannt“), wenn der DWD in dieser Datei keine
Daten für deine Gitterzelle hat, zum Beispiel während eines Radarausfalls,
statt einen Platzhalterwert zu melden. Das Protokoll meldet das einmal pro
Ausfall und noch einmal, wenn wieder Daten da sind. Die
[laufenden Summen](totals.md) überspringen diese Zeitfenster.

## Laufende Summen {#running-totals}

`Niederschlag vorige Stunde` und `Niederschlag gestern` speisen außerdem die
beiden [laufenden Summen](totals.md); sie sind die Sensoren für
Langzeitstatistiken.
