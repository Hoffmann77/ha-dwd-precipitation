---
title: Häufige Fragen
description: Häufig gestellte Fragen zu DWD Precipitation.
---

## Funktioniert es außerhalb Deutschlands? {#does-it-work-outside-germany}

Nur in einem Streifen nahe der deutschen Grenze. Die Radarkomposits des DWD
decken Deutschland und etwas Fläche darum herum ab; anderswo enthalten die
Dateien keine Daten. Siehe
[Gitterzellen-Suche](../how-it-works/grid-lookup.md#which-locations-are-covered).

## Brauche ich einen API-Schlüssel oder ein Konto? {#do-i-need-an-api-key-or-account}

Nein. Die Daten stammen von [DWD Open Data](https://opendata.dwd.de/), das
kostenlos ist und keine Registrierung braucht.

## Wie viele Daten lädt es herunter? {#how-much-data-does-it-download}

Im Mittel etwa 1 GB am Tag: Gemessen über drei Tage im Oktober 2026 lud eine
Installation etwa 0,9 GB pro Tag herunter. Das hängt vom Wetter ab, und zwar
nicht nur an deinem Standort: Die Dateien des DWD decken ganz Deutschland ab,
und Regen irgendwo macht sie größer, daher kostet ein trockener Tag weniger
und ein Tag mit verbreitetem Regen mehr.

Den größten Teil macht das RV-Archiv aus, das alle 5 Minuten vollständig
gelesen wird. RS wird teilweise gelesen (etwa ein Fünftel jedes Archivs), und
die Dateien von HymecNG und RADOLAN sind klein. Denk daran, wenn deine
Verbindung nach Volumen abgerechnet wird.

## Warum hinkt „aktuell“ ein paar Minuten hinterher? {#why-does-now-lag-a-few-minutes}

Ein Wert beschreibt das Zeitfenster des DWD, das zum Termin der
Veröffentlichung endet, und der DWD veröffentlicht ein paar Minuten danach.
`Niederschlagsintensität aktuell` ist etwa 4 bis 10 Minuten alt, wenn du sie
siehst. Siehe
[Veröffentlichungszeitpunkte](../how-it-works/release-timing.md#why-now-is-a-few-minutes-old).

## Welchen Sensor soll ich für Regenstatistiken verwenden? {#which-sensor-should-i-use-for-rain-statistics}

[`Niederschlag gesamt`](../entities/totals.md). Er wächst nur, daher können
die Statistiken von Home Assistant, die Statistikdiagramm-Karte und der
Verbrauchszähler-Helfer (Utility Meter) ihn über jeden Zeitraum summieren. Die
anderen Sensoren sind Momentaufnahmen eines Zeitfensters und lassen sich über
die Zeit nicht aufaddieren.

## Was ist der Unterschied zwischen „letzte 60 min“ und „vorige Stunde“? {#what-is-the-difference-between-last-60-min-and-previous-hour}

`Niederschlag letzte 60 min` ist ein reiner Radarwert, eine gleitende Stunde,
die alle 5 Minuten aktualisiert wird. `Niederschlag vorige Stunde` ist die
letzte volle Stunde, mit Niederschlagsmessern angeeicht und etwa 30 Minuten
nach dem Ende der Stunde verfügbar. Der erste ist schneller, der zweite
genauer. Siehe
[RADOLAN RW und SF](../entities/radolan.md#precipitation-previous-hour).

## Warum regnet es hier, aber der Sensor zeigt 0? {#why-does-it-rain-here-but-the-sensor-says-0}

- Der Wert ist vielleicht noch nicht da: Radarwerte sind ein paar Minuten alt,
  angeeichte etwa eine halbe Stunde.
- Das Radar misst in der Luft über einer 1-km-Zelle. Leichter Nieselregen oder
  ein Schauer am Rand deiner Zelle kann unter dem liegen, was es erkennt.
- `Niederschlag letzte 60 min` und `Niederschlag vorige Stunde` sind Summen:
  Ein kurzer Schauer bringt vielleicht nur ein paar Zehntel Millimeter.

## Warum ändert sich „Niederschlagsende“ ständig? {#why-does-precipitation-end-keep-changing}

Mit dem Standard *Die erste trockene Pause* meldet der Sensor das Ende des
aktuellen Schauers, und das verschiebt sich, wenn Schauer entstehen und sich
auflösen. Die Option *„Niederschlagsende“ zeigt* lässt sich für eine
stabilere Antwort auf *Ab wann kein Regen mehr vorhergesagt ist* stellen. Siehe
[RADVOR-RV-Nowcast](../entities/radvor-rv.md#precipitation-start-and-end).

## Warum ist „Niederschlagsbeginn“ unbekannt? {#why-is-precipitation-start-unknown}

Innerhalb der nächsten zwei Stunden ist kein Regen vorhergesagt, und weiter
reicht der Nowcast (die Kurzfristvorhersage) des DWD nicht.
`Niederschlag erwartet` ist dann `off`.

## Kann ich es für mehrere Standorte verwenden? {#can-i-use-it-for-several-locations}

Ja: Füge die Integration einmal pro Standort hinzu. Siehe
[Konfiguration](../getting-started/configuration.md#several-locations).

## Ist es eine offizielle Integration des DWD? {#is-it-an-official-dwd-integration}

Nein. Es ist ein Community-Projekt, das in keiner Verbindung zum Deutschen
Wetterdienst steht und nicht von ihm unterstützt wird. Es nutzt die
öffentlichen Daten des DWD gemäß dessen Nutzungsbedingungen.
