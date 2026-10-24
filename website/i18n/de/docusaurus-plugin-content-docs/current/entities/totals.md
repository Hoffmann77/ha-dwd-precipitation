---
title: Laufende Summen
description: Niederschlag gesamt und Niederschlag gesamt täglich, für die Langzeitstatistiken von Home Assistant.
---

Zwei stetig wachsende Summen allen Regens seit der Einrichtung. Sie sind für
die Langzeitstatistiken von Home Assistant da: nutze sie für tägliche,
wöchentliche, monatliche oder jährliche Regensummen. Die anderen Sensoren sind
Momentaufnahmen eines Zeitfensters und lassen sich über die Zeit nicht
korrekt aufsummieren.

| Sensor | Einheit | Addiert | Wächst |
|--------|---------|---------|--------|
| **Niederschlag gesamt** | mm | jeden Wert von `Niederschlag vorige Stunde` einmal | stündlich |
| **Niederschlag gesamt täglich** | mm | jeden Wert von `Niederschlag gestern` einmal | täglich |

Beide haben die Zustandsklasse `total_increasing` und funktionieren daher mit
den Langzeitstatistiken von Home Assistant, der Statistikdiagramm-Karte und
dem [Verbrauchszähler-Helfer (Utility Meter)](https://www.home-assistant.io/integrations/utility_meter/).

## Niederschlag gesamt {#precipitation-total}

Addiert jeden Wert von [`Niederschlag vorige Stunde`](radolan.md) einmal: die
angeeichte Summe jeder vollen Stunde. Der Sensor ist innerhalb der Stunde
aktuell und eignet sich daher auch für Automationen wie „wie viel Regen seit
heute Morgen“. Diesen Sensor solltest du nutzen.

Die Statistiken von Home Assistant sehen jede Stunde etwa eine halbe Stunde
nach ihrem Ende (11:00–12:00 wird gegen 12:28 addiert), daher rutscht nur die
letzte Stunde eines Tages in den nächsten.

## Niederschlag gesamt täglich {#precipitation-total-daily}

Addiert jeden Wert von [`Niederschlag gestern`](radolan.md) einmal. Der Regen
von heute erscheint erst am nächsten Morgen, und die Statistiken von Home
Assistant zählen ihn an dem Tag, an dem er addiert wurde, daher **erscheint
der Regen jedes Tages unter dem folgenden Tag**. Nimm lieber
`Niederschlag gesamt`, außer du willst ausdrücklich die Tagesanalyse des DWD.

Bei Installationen, die ab 2026.11.0 eingerichtet wurden, ist er
standardmäßig deaktiviert. Aktiviere ihn auf der Einstellungsseite der
Entität, wenn du ihn brauchst; er beginnt dann ab diesem Zeitpunkt zu zählen.
Installationen, die ihn schon hatten, behalten ihn aktiviert.

An den beiden Tagen der Zeitumstellung liegen die Zeitfenster bis 23:50 23
bzw. 25 Stunden auseinander, während jede Datei 24 Stunden abdeckt; daher wird
im Frühjahr eine Stunde doppelt gezählt und im Herbst eine ausgelassen.

## Wie sie zählen {#how-they-count}

- Beide beginnen bei 0, wenn die Integration eingerichtet wird, und behalten
  ihre Summe über Neustarts hinweg.
- Jede Veröffentlichung des DWD wird einmal gezählt, egal wie oft sie gesehen
  wird, und zwei gleich nasse Stunden sind trotzdem zwei Veröffentlichungen.
- Eine Datei ohne Daten für deine Gitterzelle addiert nichts.
- Sie **bleiben verfügbar, während der DWD nicht veröffentlicht**, weil die
  bisher gezählte Summe weiterhin stimmt. Die Option *„Nicht verfügbar“ anzeigen,
  wenn die Daten veraltet sind* gilt für sie nicht.

| Attribut | Bedeutung |
|----------|-----------|
| `counted_until` | Ende des neuesten DWD-Zeitfensters, das in der Summe enthalten ist, ISO-8601 UTC; `null`, bis die erste Datei ankommt |

## Verpasste Stunden werden nachgeholt {#missed-hours-are-added-late}

War Home Assistant offline oder hat der DWD eine Zeit lang nicht
veröffentlicht, werden die verpassten Dateien beim nächsten Update im
Hintergrund abgerufen und nachträglich addiert. Die Liste der verpassten
Dateien wird mit der Summe gespeichert, sodass sie nach einem Neustart
mittendrin fortgesetzt wird, und eine Datei, deren Download fehlschlägt, wird
mit jeder neuen erneut versucht, solange der DWD sie vorhält: 48 Stunden für
`Niederschlag gesamt` und nur den Vortag für `Niederschlag gesamt täglich`.
Nur Dateien, die der DWD nicht mehr anbietet, bleiben außen vor, und das
Protokoll meldet das.

Nachträglich addierter Regen zählt in den Statistiken von Home Assistant zu
dem Zeitpunkt, an dem er addiert wurde, nicht in der Stunde, in der er
gefallen ist. `counted_until` geht dafür nicht zurück.

## Beispiel: Regen in diesem Monat {#example-rain-this-month}

Ein [Verbrauchszähler-Helfer (Utility Meter)](https://www.home-assistant.io/integrations/utility_meter/),
der monatlich zurückgesetzt wird, in `configuration.yaml`:

```yaml
utility_meter:
  rain_this_month:
    source: sensor.home_precipitation_total
    cycle: monthly
```

Denselben Helfer kannst du in der Oberfläche unter **Einstellungen > Geräte &
Dienste > Helfer > Helfer erstellen > Verbrauchszähler** anlegen.

## Warum es zwei gibt {#why-there-are-two}

Es sind getrennte Entitäten statt einer mit einer Option für die Quelle, weil
ein Wechsel der Quelle einen `total_increasing`-Sensor springen ließe. Die
Begründung steht in [ADR 0005](/development/adr/0005-running-totals).
