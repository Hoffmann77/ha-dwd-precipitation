---
title: RADVOR-RV-Nowcast
description: Niederschlagsintensität aktuell, Spitzenintensitäten, Beginn und Ende des Regens, Niederschlag erwartet und die nasseste Stunde voraus.
---

RADVOR RV ist der Radar-Nowcast (Kurzfristvorhersage) des DWD in
5-Minuten-Schritten. Alle 5 Minuten veröffentlicht der DWD 25 Schritte: die
zuletzt gemessenen 5 Minuten (die Analyse) und 24 Vorhersageschritte, die zwei
Stunden vorausreichen. Daraus leitet die Integration ab, wie stark es regnet,
wie stark es regnen wird, wann Regen beginnt und aufhört, und die nasseste
Stunde voraus.

## Niederschlagsintensität aktuell {#precipitation-intensity-now}

**Niederschlagsintensität aktuell** (mm/h) ist die Regenrate in der neuesten
Radaranalyse: die 5 Minuten, die zum Termin der DWD-Veröffentlichung enden,
auf eine Stundenrate hochgerechnet (1 mm in 5 Minuten = 12 mm/h). Der Sensor
wird alle 5 Minuten aktualisiert; das Fenster, das er beschreibt, endete etwa
4 bis 10 Minuten, bevor der Wert erscheint.

Er ist `unknown` („Unbekannt“), wenn das Radar keine Daten für deinen Standort
hat.

| Attribut | Bedeutung |
|----------|-----------|
| `window_start` / `window_end` | Beginn und Ende der 5-Minuten-Analyse, ISO-8601 UTC |
| `amount_5min` | Der Regen in diesem Fenster in mm, vor der Umrechnung in mm/h; `null` ohne Daten |

## Spitzenintensitäten {#peak-intensities}

Die stärkste Regenrate (mm/h), die in einem Fenster erwartet wird. Sie
unterscheiden Nieselregen von einem Wolkenbruch; die
[RS-Sensoren](radvor-rs.md) liefern die Mengen.

| Sensor | Fenster |
|--------|---------|
| **Spitzenintensität nächste 60 min** | die nächste Stunde |
| **Spitzenintensität nächste 60–120 min** | die zweite Stunde voraus |
| **Spitzenintensität nächste 120 min** | die ganzen zwei Stunden: der größere der beiden Werte oben |

`Spitzenintensität nächste 120 min` eignet sich für einen einzigen Auslöser
„Starkregen im Anmarsch“.

## Maximaler Stundenniederschlag {#peak-hourly-precipitation}

**Maximaler Stundenniederschlag nächste 120 min** (mm) ist die größte
Regenmenge, die in irgendeinem 60-Minuten-Fenster innerhalb der nächsten zwei
Stunden fallen soll, geprüft in 5-Minuten-Schritten. Er ist `0`, wenn kein
Regen vorhergesagt ist.

Ein Wolkenbruch, der über die Ein-Stunden-Marke reicht, zeigt sich hier
vollständig, während `Niederschlag nächste 60 min` und
`Niederschlag nächste 60–120 min` jeweils nur einen Teil davon sehen. Das
entspricht der Art, wie der DWD seine Starkregenwarnungen definiert (eine
Menge pro Stunde), und eignet sich daher für Warn-Automationen.

Er wird aus der 5-Minuten-Vorhersage von RV berechnet, die sich zu den
gleitenden Stunden von RS aufsummiert. In den seltenen Gitterzellen, in denen
die beiden Produkte des DWD voneinander abweichen, kann er unter
`Niederschlag nächste 60 min` liegen (um bis zu etwa einen halben Millimeter),
was sonst nie vorkommt.

| Attribut | Bedeutung |
|----------|-----------|
| `window_start` / `window_end` | Beginn und Ende der nassesten Stunde, ISO-8601 UTC; `null`, wenn kein Regen vorhergesagt ist. Bei zwei gleichen Fenstern das frühere |
| `forecast_rolling_1h` | Die Reihe der Stunden, aus denen der Sensor wählt, siehe unten |

### Die Reihe der gleitenden Stunden {#the-rolling-hour-series}

`forecast_rolling_1h` hat alle 5 Minuten einen Eintrag, jeweils mit dem Regen
in der Stunde von `start` bis `end` (in mm); `lead` sind die Minuten vom
Termin der Veröffentlichung bis `end`. Um 14:00 reichen die Einträge von
14:00–15:00 bis 15:00–16:00, 13 Einträge, und der Sensor zeigt den größten.

Mit der erweiterten Option
[*Vergangene Stunde in die stündliche Vorhersagereihe aufnehmen*](../getting-started/configuration.md#past-hour-in-the-series)
beginnt die Reihe eine Stunde früher, bei 13:00–14:00 (25 Einträge), sodass
ein Diagramm die vergangene Stunde und die Vorhersage als eine Kurve zeigt.
Der erste Eintrag ist dann dieselbe Stunde wie `Niederschlag letzte 60 min`,
aus den 5-Minuten-Analysen des DWD aufsummiert, sodass die beiden in seltenen
Gitterzellen leicht voneinander abweichen. Die früheren Einträge erscheinen,
sobald die Integration eine volle Stunde an Veröffentlichungen gesehen hat;
bis zu einer Stunde nach einem Neustart hat die Reihe also 13 Einträge.

## Niederschlagsbeginn und -ende {#precipitation-start-and-end}

**Niederschlagsbeginn** ist der Zeitpunkt, zu dem Regen einsetzt,
**Niederschlagsende** der, zu dem er aufhört, innerhalb der
Zwei-Stunden-Vorhersage.

- `Niederschlagsbeginn` ist jetzt (bzw. `0` Minuten), wenn es schon regnet,
  und `unknown`, wenn innerhalb von zwei Stunden kein Regen vorhergesagt ist.
- `Niederschlagsende` ist `unknown`, wenn der Regen über zwei Stunden hinaus
  anhält. Das heißt „regnet in zwei Stunden immer noch“, nicht „nie“.

Was als Regen zählt, legt die Option
[*Schwelle für Regenerkennung*](../getting-started/configuration.md#rain-detection-threshold)
fest. Standardmäßig zählt jede Menge, die der DWD erkennt.

**Format.** Die Option
[*Anzeige von „Niederschlagsbeginn“ und „Niederschlagsende“*](../getting-started/configuration.md#start-and-end-format)
macht beide Sensoren entweder zu Zeitstempeln (Standard) oder zu Dauern in
Minuten. Die jeweils andere Form ist immer als Attribut verfügbar:

| Attribut | Bedeutung |
|----------|-----------|
| `at` | Der Zeitpunkt des Ereignisses, ISO-8601 UTC (wenn der Zustand Minuten sind) |
| `minutes_until` | Ganze Minuten bis zum Ereignis (wenn der Zustand eine Uhrzeit ist) |

**Wann der Regen als beendet gilt.** Die erweiterte Option
[*Wann „Niederschlagsende“ den Regen als beendet ansieht*](../getting-started/configuration.md#end-algorithm)
wählt eine von zwei Antworten:

- **Erste trockene Lücke** (Standard): das Ende des aktuellen Schauers. Bei
  Schauerwetter springt der Wert, da jede Lücke zwischen zwei Zellen ein Ende
  ist.
- **Niederschlag endet innerhalb von 2 h:** das Ende des letzten Regens in der
  Vorhersage, nach dem innerhalb des Horizonts nichts mehr erwartet wird.
  Ruhiger, bleibt aber länger `unknown`.

## Niederschlag erwartet {#precipitation-expected}

**Niederschlag erwartet** ist ein Binärsensor: `on`, wenn innerhalb der
nächsten zwei Stunden Regen vorhergesagt ist, mit derselben
[*Schwelle für Regenerkennung*](../getting-started/configuration.md#rain-detection-threshold)
wie `Niederschlagsbeginn`.

| Attribut | Bedeutung |
|----------|-----------|
| `at` / `minutes_until` | Wann der vorhergesagte Regen beginnt; `null`, wenn keiner erwartet wird |
| `forecast_5min` | Die vollständige Vorhersage mit 25 Schritten, siehe unten |

`forecast_5min` listet die Analyse und die 24 Vorhersageschritte auf (0 bis
120 Minuten in 5-Minuten-Schritten). Jeder Schritt hat `lead` (Minuten ab dem
Termin der Veröffentlichung), `start`, `end`, `value` (mm in diesen 5 Minuten)
und `intensity` (mm/h). `value` und `intensity` sind `null` für einen Schritt
ohne Daten. Das Attribut ist immer vorhanden, damit Blueprints und Diagramme es
nutzen können, und wird nicht im Verlauf aufgezeichnet.

Ein Template, das den vorhergesagten Regen der nächsten 30 Minuten addiert:

```jinja2
{{ state_attr('binary_sensor.home_precipitation_expected', 'forecast_5min')
   | selectattr('lead', 'gt', 0) | selectattr('lead', 'le', 30)
   | map(attribute='value') | reject('none') | sum | round(2) }}
```

## Gut zu wissen {#good-to-know}

- **Nur Radar**, wie RS: Die Werte können von einem Niederschlagsmesser und
  von den [RADOLAN](radolan.md)-Sensoren abweichen.
- **Zwei-Stunden-Horizont.** Der Nowcast des DWD endet zwei Stunden voraus.
  Alles, was danach kommt, kennen diese Sensoren nicht; deshalb können Beginn
  und Ende `unknown` sein.
- [Regenereignisse](rain-events.md) werden, falls eingeschaltet, aus denselben
  RV-Schritten gebildet.
