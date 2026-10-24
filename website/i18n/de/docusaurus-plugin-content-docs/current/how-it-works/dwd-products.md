---
title: Die DWD-Produkte
description: Was RADVOR RS und RV, HymecNG sowie RADOLAN RW und SF sind und wie sie sich unterscheiden.
---

Der Deutsche Wetterdienst (DWD) betreibt ein Netz von Wetterradaren und
fasst deren Abtastungen alle 5 Minuten zu deutschlandweiten Kompositen
zusammen. Außerdem korrigiert er die Radarschätzungen mit den Messungen
seines Netzes von Niederschlagsmessern. Mehrere dieser Produkte erscheinen
auf [DWD Open Data](https://opendata.dwd.de/), kostenlos und ohne
Registrierung. Die Integration liest fünf davon.

## Nur Radar: RADVOR und HymecNG {#radar-only-radvor-and-hymecng}

**RADVOR** ist der radarbasierte Nowcast (Kurzfristvorhersage) des DWD. Er
nimmt das neueste Radarkomposit, verfolgt, wie sich der Niederschlag bewegt,
und schreibt ihn bis zu zwei Stunden in die Zukunft fort. Alle 5 Minuten
veröffentlicht er zwei Produkte, die die Integration liest:

- **RS**: 25 gleitende 60-Minuten-Summen, von der gerade gemessenen Stunde
  bis zur Stunde, die in zwei Stunden endet. Dahinter stehen
  [Niederschlag letzte 60 min und die Vorhersagen für die nächsten Stunden](../entities/radvor-rs.md).
- **RV**: 25 Schritte zu 5 Minuten, der neueste gemessene und 24
  Vorhersageschritte. Dahinter stehen
  [Intensität, Spitzenwerte, Beginn und Ende](../entities/radvor-rv.md).

Die Stunden von RS sind die Summen der 5-Minuten-Schritte von RV, in fast
jeder Zelle exakt.

**HymecNG** ist die Hydrometeorklassifikation des DWD: Alle 5 Minuten
bestimmt sie aus den Radarmessungen, welche Art von Niederschlag fällt, etwa
Regen, Nieselregen, Schnee oder Hagel. Dahinter steht
[Niederschlagsart aktuell](../entities/hymecng.md).

Reine Radarwerte sind schnell und fein aufgelöst, aber ein Radar misst in der
Luft über dem Boden, aus der Stärke des Echos. Seine Schätzung kann von dem
abweichen, was ein Niederschlagsmesser am Boden auffängt, in beide
Richtungen.

## Angeeicht: RADOLAN {#gauge-adjusted-radolan}

**RADOLAN** verbindet das Radarkomposit mit den Messungen der
Niederschlagsmesser des DWD, sodass die räumliche Auflösung des Radars an die
tatsächlich am Boden gemessenen Mengen angeglichen wird. Dafür braucht es die
Meldungen der Messer, deshalb erscheint RADOLAN etwa eine halbe Stunde nach
dem Ende seines Zeitfensters. Die Integration liest:

- **RW**: eine Stunde Niederschlag. Der DWD berechnet sie alle 10 Minuten für
  die Stunde, die dann endet; die Integration nutzt die Läufe, die zur vollen
  Stunde enden. Dahinter stehen
  [Niederschlag vorige Stunde](../entities/radolan.md) und
  [Niederschlag gesamt](../entities/totals.md).
- **SF**: 24 Stunden Niederschlag, für Zeitfenster, die um :50 enden.
  Dahinter stehen
  [Niederschlag letzte 24h und gestern](../entities/radolan.md).

## Das Gitter {#the-grid}

Alle fünf Produkte liegen auf demselben Gitter, dem „DE1200“ des DWD:
1100 × 1200 Zellen zu 1 km × 1 km, die Deutschland und einen Streifen darum
abdecken. Die Integration liest die eine Zelle, die deinen Standort enthält;
siehe [Gitterzellen-Suche](grid-lookup.md).

## Dateien und Datenmenge {#files-and-data-volume}

| Produkt | Veröffentlicht als | Gelesen |
|---------|--------------------|---------|
| RS | ein Archiv aus 25 HDF5-Dateien alle 5 min, je nach Regen in Deutschland unter 1 MB bis etwa 17,5 MB | die drei Stunden, die die Integration braucht, per Range-Anfrage (HTTP-Teildownload), etwa ein Fünftel des Archivs |
| RV | ein Archiv aus 25 HDF5-Dateien alle 5 min, ähnlich groß | das ganze Archiv |
| HymecNG | eine HDF5-Datei alle 5 min | die ganze Datei |
| RW, SF | eine kleine HDF5-Datei pro Lauf | die ganze Datei |

Die Radardateien werden auf deinem Home-Assistant-Rechner dekodiert,
außerhalb seiner Event-Loop, sodass selbst ein Raspberry Pi reaktionsfähig
bleibt. Kein anderer Dienst ist beteiligt: Die Integration spricht nur mit
`opendata.dwd.de`.

## Nutzungsbedingungen {#terms-of-use}

Die Daten sind © Deutscher Wetterdienst und werden gemäß den
[Nutzungsbedingungen von DWD Open Data](https://www.dwd.de/EN/service/legal_notice/legal_notice_node.html)
verwendet. Der DWD veröffentlicht den
[aktuellen Status seiner Radarstationen](https://www.dwd.de/DE/leistungen/radarniederschlag/rn_info/home_freie_radarstatus_kartendaten.html),
der die meisten Lücken in den Daten erklärt.
