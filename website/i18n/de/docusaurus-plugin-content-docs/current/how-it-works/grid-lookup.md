---
title: Gitterzellen-Suche
description: Wie aus deinem Standort eine 1-km-Gitterzelle des Radars wird und welche Standorte abgedeckt sind.
---

Die Radarprodukte des DWD sind Gitter, keine Punktvorhersagen. Die
Integration meldet den Wert der einen Gitterzelle, die deinen Standort
enthält.

## Das Gitter {#the-grid}

Alle Produkte liegen auf dem „DE1200“-Gitter des DWD: 1100 × 1200 Zellen zu
1 km × 1 km in einer polarstereografischen Projektion, die Deutschland und
einen Streifen jenseits seiner Grenzen abdecken. Wo das Gitter über das
hinausreicht, was die Radare des DWD sehen, enthalten seine Zellen keine
Daten. Jede Zelle enthält einen Wert pro Datei: eine Menge, eine Rate oder
eine Klasse.

Die Sensoren beschreiben also ein Quadrat von etwa 1 km um deinen Standort.
Zwei Orte, die ein paar hundert Meter auseinanderliegen, lesen meist dieselbe
Zelle; ein Nachbar 1 km entfernt kann einen Sommerschauer anders sehen.

## Die Zelle finden {#finding-the-cell}

Deine geografische Breite und Länge werden auf das Gitter projiziert, und
die Integration nimmt die Zelle, *in die* dein Punkt fällt, nicht die, deren
Mittelpunkt zufällig am nächsten liegt. Das entspricht der Art, wie der DWD
das Gitter definiert, sodass der Wert derjenige ist, den die eigenen
Werkzeuge des DWD für deinen Standort zeigen.

Die Integration liest das Gitter, das jede Datei in ihrem Kopf beschreibt,
statt einer Kopie des Gitters im Code. Sollte der DWD ein Gitter jemals
verschieben oder seine Größe ändern, liest die Integration weiterhin die
Zelle, die deinen Standort enthält. Eine Datei auf einem Gitter, das sie
nicht interpretieren kann, wird abgelehnt, statt an der falschen Zelle
gelesen zu werden.

## Welche Standorte abgedeckt sind {#which-locations-are-covered}

- **Bei der Einrichtung** wird ein Standort akzeptiert, wenn er in einem
  Rechteck um das Gitter liegt (Breite 45,6° bis 56,3°, Länge 1,4° bis
  18,8°). Dieses Rechteck ist größer als das Gitter, da bei der Einrichtung
  keine Datei zur Hand ist.
- **Wenn ein Produkt gelesen wird**, wird ein Standort außerhalb seines
  Gitters im Protokoll gemeldet: *The configured location is not on the grid
  of the … release: DWD's radar does not cover it.* Richte die Integration
  dann mit einem Standort innerhalb Deutschlands neu ein.
- **Nahe den Grenzen** reicht das Gitter weiter, als die Radare sehen. Eine
  Zelle ohne Radarabdeckung enthält „keine Daten“, und ihre Sensoren sind
  `unknown` („Unbekannt“). Das Protokoll warnt dann direkt nach der
  Einrichtung, dass es für deinen Standort keine Radardaten gibt.

## Keine Daten für eine Zelle {#no-data-for-a-cell}

Auch innerhalb Deutschlands kann eine Zelle eine Weile ohne Daten sein: Wenn
ein Radar außer Betrieb ist, erstellt der DWD das Komposit ohne es, und die
Zellen, die nur dieses Radar abgedeckt hat, sind leer. Die Sensoren sind dann
`unknown`, und das Protokoll nennt das fehlende Radar, wenn es das erkennen
kann. Siehe
[Verfügbarkeit und Aktualität](availability.md#no-data-for-your-location).
