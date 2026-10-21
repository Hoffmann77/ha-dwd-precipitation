---
title: Verfügbarkeit und Aktualität
description: Wann Sensoren nicht verfügbar oder unbekannt werden, wie lange ein Wert gehalten wird, während der DWD spät dran ist, und warum ein ausgefallenes Produkt die anderen nicht beeinträchtigt.
---

Ein Sensor kann aus zwei verschiedenen Gründen ohne aktuellen Wert sein, und
die beiden zeigen sich unterschiedlich:

| Zustand | Ursache | Was zu tun ist |
|---------|---------|----------------|
| `unavailable` („Nicht verfügbar“) | Die Integration hat keine aktuelle Datei für das Produkt: Der DWD ist spät dran, oder Open Data ist nicht erreichbar | Nichts; er erholt sich beim nächsten erfolgreichen Abruf |
| `unknown` („Unbekannt“) | Die Datei ist da, enthält aber keinen Wert für deinen Standort (ein Radarausfall), oder es gibt nichts zu melden (kein Regen vorhergesagt für `Niederschlagsbeginn`) | Bei einem Ausfall nichts; er erholt sich mit der nächsten Datei, die Daten hat |

## Wenn ein Wert veraltet {#when-a-value-goes-out-of-date}

Während der DWD spät dran ist, wird der letzte Wert eine Weile gehalten: Eine
Datei, die ein paar Minuten zu spät kommt, soll dein Dashboard nicht leeren.
Die Sensoren eines Produkts werden `unavailable`, sobald die Datei, die ihren
Wert hätte ersetzen sollen, mehr als **6 Minuten überfällig** ist
(**30 Minuten** für `Niederschlag gestern`).

Die Uhr beginnt zu laufen, wenn die nächste Datei auf Open Data hätte sein
sollen, nicht wenn der aktuelle Wert veröffentlicht wurde. Für RS, während
die Veröffentlichung zum Termin 14:00 angezeigt wird:

- die Veröffentlichung zum Termin 14:05 ist gegen 14:09 fällig,
- ist sie bis etwa 14:15 nicht angekommen, werden die RS-Sensoren
  `unavailable`,
- sie kommen zurück, sobald irgendeine neuere Veröffentlichung abgerufen
  wird.

Die Frist ist für stündliche und tägliche Produkte dieselbe, denn sie misst,
wie lange der DWD zum Veröffentlichen Zeit bekommt, nicht wie alt ein Wert
sein darf. Die erneuten Versuche laufen die ganze Zeit weiter, siehe
[Veröffentlichungszeitpunkte](release-timing.md#when-dwd-is-late).

### Stattdessen den letzten Wert behalten {#keeping-the-last-value-instead}

Ist die erweiterte Option
[*Sensoren als nicht verfügbar anzeigen, wenn die Daten veraltet sind*](../getting-started/configuration.md#unavailable-when-out-of-date)
ausgeschaltet, behalten die Sensoren immer ihren neuesten Wert, egal wie alt.
Das passt zu Dashboards, die nie eine Lücke zeigen sollen, aber der Wert kann
dann Stunden alt sein, ohne dass man es ihm ansieht. Die Attribute mit den
technischen Details (`source_timestamp`) verraten dir, wie alt er ist.

### Ausnahmen {#exceptions}

- Die [laufenden Summen](../entities/totals.md) bleiben immer verfügbar: Die
  bisher gezählte Summe stimmt weiterhin, und verpasste Stunden werden
  nachträglich addiert.
- [Zeitraum ohne Niederschlag](../entities/dry-streak.md) folgt der
  Verfügbarkeit seines Quellprodukts.

## Keine Daten für deinen Standort {#no-data-for-your-location}

Fällt ein Radar aus dem Komposit des DWD heraus, sind die Zellen, die nur es
abgedeckt hat, ohne Daten, während sich jede Datei weiterhin problemlos
herunterladen lässt. Die Sensoren dieses Produkts sind dann `unknown`. Das
Protokoll bekommt eine Warnung, wenn die Daten wegfallen, die das oder die
fehlenden Radare nennt, wenn es das erkennen kann, und eine Meldung, wenn sie
zurück sind, und nichts dazwischen.

Erscheint diese Warnung direkt nach der Einrichtung und kommen nie Daten an,
liegt der Standort außerhalb des Gebiets, das dieses Produkt abdeckt; siehe
[Gitterzellen-Suche](grid-lookup.md#which-locations-are-covered).

## Jedes Produkt für sich {#one-product-at-a-time}

Jedes DWD-Produkt wird nach seinem eigenen Zeitplan abgerufen, und seine
Fehler betreffen nur seine eigenen Sensoren. Stellt der DWD die
Veröffentlichung eines Produkts ein, werden dessen Sensoren nicht verfügbar,
während alle anderen weiterarbeiten, und das Protokoll sagt, welches
ausgefallen ist. Die Integration startet nur dann nicht, wenn *jedes* Produkt
scheitert, zum Beispiel ohne Internetverbindung; Home Assistant versucht die
Einrichtung dann selbst erneut.
