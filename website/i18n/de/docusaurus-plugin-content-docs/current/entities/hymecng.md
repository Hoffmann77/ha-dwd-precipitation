---
title: Niederschlagsart (HymecNG)
description: Niederschlagsart aktuell, aus der HymecNG-Radarklassifikation des DWD.
---

HymecNG ist die Klassifikation des DWD, was gerade fällt, alle 5 Minuten aus
Radardaten abgeleitet. Die Integration liest die Klasse deiner Gitterzelle.

## Niederschlagsart aktuell {#precipitation-type-now}

**Niederschlagsart aktuell** ist ein Enum-Sensor: was gerade fällt, aus der
neuesten 5-Minuten-Analyse, wie bei
[Niederschlagsintensität aktuell](radvor-rv.md#precipitation-intensity-now).

| Zustand | Angezeigt als |
|---------|---------------|
| `no_precipitation` | Kein Niederschlag |
| `not_classified` | Nicht klassifiziert |
| `drizzle` | Nieselregen |
| `rain` | Regen |
| `freezing_drizzle` | Gefrierender Nieselregen |
| `freezing_rain` | Gefrierender Regen |
| `sleet` | Schneeregen |
| `snow` | Schnee |
| `graupel` | Graupel |
| `hail` | Hagel |
| `large_hail` | Großer Hagel |

Automationen und Templates verwenden den Zustand links; das Dashboard zeigt
die übersetzte Bezeichnung rechts.

## Kein Niederschlag oder unbekannt {#no-precipitation-or-unknown}

Die Datei des DWD unterscheidet zwei Situationen, und der Sensor ebenso:

- **`no_precipitation`**: Das Radar hat deinen Standort abgetastet und kein
  Echo gesehen. Es ist trocken.
- **`unknown`** („Unbekannt“): Die Datei hat keine Daten für deinen Standort:
  Ein Radar fehlt im Radarkomposit des DWD, oder der Standort liegt
  außerhalb des Gebiets, das HymecNG abdeckt. Das Protokoll sagt einmal,
  welcher der beiden Fälle vorliegt.

## Beispiel {#example}

Benachrichtigen, wenn zu Hause gefrierender Regen klassifiziert wird:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.home_precipitation_type_now
    to:
      - freezing_drizzle
      - freezing_rain
actions:
  - action: notify.notify
    data:
      message: "Gefrierender Regen zu Hause: Vorsicht, Glatteis."
```
