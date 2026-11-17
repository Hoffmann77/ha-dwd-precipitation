---
title: Stündlicher Niederschlagsverlauf
description: Der angeeichte Regen jeder vergangenen Stunde an deinem Ort, für Blueprints, die Regen über mehrere Stunden oder Tage betrachten.
---

Der Sensor **Stündlicher Niederschlagsverlauf**
(`sensor.<name>_hourly_precipitation_history`) speichert den Regen jeder
vergangenen vollen Stunde an deinem Ort: standardmäßig die letzten 72
Stunden, jede mit ihrer Zeit. Er ist für Blueprints gedacht, die Regen über
mehrere Stunden oder Tage beurteilen, etwa Warnungen vor Dauerregen oder
einen Bericht, wie viel seit gestern gefallen ist.

Jede Stunde ist die angeeichte Analyse des DWD, der Wert,
den [`Niederschlag vorige Stunde`](radolan.md) für diese Stunde zeigt. Ein
Template-Sensor, der diesen Wert festhält, verpasst jede Stunde, in der Home
Assistant aus war; dieser Sensor speichert sie auf der Festplatte und füllt
sie danach auf.

## Einschalten {#turning-it-on}

Der Sensor ist standardmäßig aus. Schalte ihn in den Optionen ein, Abschnitt
*Stündlicher Niederschlagsverlauf*, mit
[*Sensor „Stündlicher Niederschlagsverlauf“ hinzufügen*](../getting-started/configuration.md#hourly-history),
und wähle dort, wie viele Stunden er speichert. Ausschalten entfernt den
Sensor und löscht die gespeicherten Stunden.

Er ist ein Diagnose-Sensor und erscheint daher auf der Geräteseite unter
*Diagnose* statt bei den anderen Sensoren.

## Zustand und Attribute {#state-and-attributes}

Der Zustand ist das Ende der neuesten gespeicherten Stunde, als Zeit. Er
ändert sich einmal pro Stunde, etwa 30 Minuten nach Stundenende, wenn der DWD
sie veröffentlicht.

| Attribut | Bedeutung |
|----------|-----------|
| `hours` | Jede gespeicherte Stunde, älteste zuerst: das Ende der Stunde (UTC) und ihr Regen in mm. `null`, wenn die Datei des DWD für deinen Ort keine Daten hatte (ein Radarausfall). |
| `missing` | Die Stunden des Zeitfensters, die nicht gespeichert sind, älteste zuerst, nach ihrem Ende. |
| `hours_kept` | Wie viele Stunden das Zeitfenster umfasst (die Option *Gespeicherte Stunden*). |

```yaml
# Zustand: 2026-11-17T14:00:00+00:00
hours:
  "2026-11-14T17:00:00+00:00": 0.4
  "2026-11-14T18:00:00+00:00": null
  …
missing:
  - "2026-11-15T03:00:00+00:00"
hours_kept: 72
```

Das Zeitfenster endet immer an der neuesten Stunde, die der DWD inzwischen
veröffentlicht haben sollte. Verspätet sich der DWD, steht diese Stunde in
`missing`, statt zu fehlen, sodass ein Blueprint ein unvollständiges
Zeitfenster von einem trockenen unterscheiden kann: Ein Zeitfenster ist
vollständig, wenn keine seiner Stunden in `missing` steht.

Der Sensor bleibt verfügbar, während sich der DWD verspätet, denn die schon
gespeicherten Stunden stimmen weiterhin. Keines seiner Attribute wird in der
Verlaufsdatenbank von Home Assistant gespeichert.

## Fehlende Stunden {#missing-hours}

Eine Stunde fehlt, wenn Home Assistant aus war, als der DWD sie
veröffentlicht hat, oder der DWD sie nicht rechtzeitig veröffentlicht hat.
Mit eingeschalteter Option
[*Fehlende Daten beim DWD abrufen*](../getting-started/configuration.md#hourly-history-fetch)
(Standard) lädt die Integration fehlende Stunden herunter, je etwa 30 KB, im
Hintergrund nach jeder neuen Stunde, die neueste zuerst. Ein fehlgeschlagener
Download wird mit der nächsten Stunde wiederholt.

Der DWD hält nur die letzten 48 Stunden auf seinem Server bereit. Eine ältere
Stunde, die verpasst wurde, bleibt in `missing`, bis sie das Zeitfenster
verlässt; beim Standard von 72 Stunden hinterlässt ein Ausfall von mehr als
zwei Tagen eine Lücke.

Ist die Option aus, werden nur Stunden gespeichert, die die Integration
ohnehin liest: jede Stunde die aktuelle und die, die
[`Niederschlag gesamt`](totals.md) oder
[`Zeitraum ohne Niederschlag`](dry-streak.md) nach einem Ausfall selbst
herunterladen. Stunden, die der Verlauf schon enthält, werden für diese
Sensoren nie erneut heruntergeladen.

## Zusammen mit Regenereignissen {#together-with-rain-events}

Die neueste Stunde endet etwa 30 bis 90 Minuten vor jetzt. Für die Zeit
danach hat der Sensor [`Regenereignisse`](rain-events.md) die
5-Minuten-Schritte des Radars der letzten zwei Stunden in seinem Attribut
`measured`, und seine Vorhersage in `steps`. Ein Blueprint, der den Regen bis
jetzt oder bis zwei Stunden voraus braucht, fügt diese nach der neuesten
Stunde an: Die Stunden enden zur vollen Stunde und die Schritte auf
5-Minuten-Marken, sodass nichts doppelt gezählt wird.

Mit *Fehlende Daten beim DWD abrufen* werden auch Radarschritte abgerufen,
die nach der neuesten Stunde verpasst wurden (etwa während eines Neustarts).
Schritte in `measured` vor der neuesten Stunde können `null` bleiben; die
Stunde deckt sie ab.

## Beispiel: der Regen der letzten 6 Stunden {#example-the-rain-of-the-last-6-hours}

```jinja
{% set h = state_attr('sensor.home_hourly_precipitation_history', 'hours') %}
{% set ends = (h | list)[-6:] %}
{{ ends | map('extract', h) | reject('none') | sum | round(1) }}
```

Prüfe zusätzlich `missing`, wenn das Ergebnis alle sechs Stunden abdecken
muss.
