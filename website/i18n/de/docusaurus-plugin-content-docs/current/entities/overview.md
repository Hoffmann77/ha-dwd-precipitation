---
title: Entitäten
description: Alle Entitäten von DWD Precipitation auf einen Blick, und wie ihre Namen aufgebaut sind.
---

Alle Entitäten gehören zu einem **DWD Precipitation**-Gerät pro eingerichtetem
Standort, außer den [Regenwarnungen](rain-warnings.md), die je ein eigenes
Gerät sind. Ihre IDs beginnen mit dem Namen, den du dem Standort gegeben hast:
mit dem Namen `Home` ist `Niederschlag letzte 60 min`
`sensor.home_precipitation_last_60_min`.

:::note[Vor 2026.11.0 installiert?]

Installationen, die vor 2026.11.0 eingerichtet wurden, behalten ihre alten
Entitäts-IDs; nur die Namen haben sich geändert.
[Aktualisieren](../help/upgrading.md#renamed-entities) listet die IDs auf, die
sie behalten haben.

:::

## Die Namen lesen {#reading-the-names}

Ein Name nennt nur dann ein Zeitfenster, wenn das Fenster zum Wert gehört:

| Name | Bedeutung | Beispiele |
|------|-----------|-----------|
| `letzte <N>` | gemessene Summe über das Fenster, das mit der neuesten DWD-Veröffentlichung endet | `Niederschlag letzte 60 min`, `Niederschlag letzte 24h` |
| `nächste <N>` | Vorhersage über ein Fenster ab jetzt | `Niederschlag nächste 60 min`, `Niederschlag nächste 60–120 min` |
| `vorige Stunde`, `gestern` | die letzte vollständige volle Stunde bzw. der letzte vollständige Kalendertag | `Niederschlag vorige Stunde`, `Niederschlag gestern` |
| `aktuell` | die neueste 5-Minuten-Radaranalyse | `Niederschlagsintensität aktuell`, `Niederschlagsart aktuell` |

Die Entitäts-IDs werden aus den englischen Namen gebildet, deshalb steht dort
`last`, `next`, `previous_hour`, `yesterday` und `now`:
`Niederschlag vorige Stunde` ist `sensor.<name>_precipitation_previous_hour`.

Der Radar-Nowcast (Kurzfristvorhersage) gibt seine Fenster in Minuten an,
passend zu seinen 5-Minuten-Schritten: `nächste 60–120 min` ist die *zweite*
Stunde voraus. Die angeeichten Analysen verwenden Stunden und Tage.

„Aktuell“ ist die neueste Radaranalyse; sie umfasst die fünf Minuten, die zum
Termin der DWD-Veröffentlichung enden. Wenn der Wert in Home Assistant
erscheint, ist dieses Fenster schon etwa 3 bis 10 Minuten vorbei. Siehe
[Veröffentlichungszeitpunkte](../how-it-works/release-timing.md).

## Alle Entitäten {#all-entities}

| Entität | Entitäts-ID | Einheit | Aktualisiert | Details |
|---------|-------------|---------|--------------|---------|
| Niederschlag letzte 60 min | `sensor.<name>_precipitation_last_60_min` | mm | 5 min | [RADVOR RS](radvor-rs.md) |
| Niederschlag nächste 60 min | `sensor.<name>_precipitation_next_60_min` | mm | 5 min | [RADVOR RS](radvor-rs.md) |
| Niederschlag nächste 60–120 min | `sensor.<name>_precipitation_next_60_120_min` | mm | 5 min | [RADVOR RS](radvor-rs.md) |
| Niederschlag nächste 120 min | `sensor.<name>_precipitation_next_120_min` | mm | 5 min | [RADVOR RS](radvor-rs.md) |
| Niederschlagsintensität aktuell | `sensor.<name>_precipitation_intensity_now` | mm/h | 5 min | [RADVOR RV](radvor-rv.md#precipitation-intensity-now) |
| Spitzenintensität nächste 60 min | `sensor.<name>_peak_intensity_next_60_min` | mm/h | 5 min | [RADVOR RV](radvor-rv.md#peak-intensities) |
| Spitzenintensität nächste 60–120 min | `sensor.<name>_peak_intensity_next_60_120_min` | mm/h | 5 min | [RADVOR RV](radvor-rv.md#peak-intensities) |
| Spitzenintensität nächste 120 min | `sensor.<name>_peak_intensity_next_120_min` | mm/h | 5 min | [RADVOR RV](radvor-rv.md#peak-intensities) |
| Maximaler Stundenniederschlag nächste 120 min | `sensor.<name>_peak_hourly_precipitation_next_120_min` | mm | 5 min | [RADVOR RV](radvor-rv.md#peak-hourly-precipitation) |
| Niederschlagsbeginn | `sensor.<name>_precipitation_start` | Uhrzeit oder min | 5 min | [RADVOR RV](radvor-rv.md#precipitation-start-and-end) |
| Niederschlagsende | `sensor.<name>_precipitation_end` | Uhrzeit oder min | 5 min | [RADVOR RV](radvor-rv.md#precipitation-start-and-end) |
| Niederschlag erwartet | `binary_sensor.<name>_precipitation_expected` | an/aus | 5 min | [RADVOR RV](radvor-rv.md#precipitation-expected) |
| Niederschlagsart aktuell | `sensor.<name>_precipitation_type_now` | Zustand | 5 min | [HymecNG](hymecng.md) |
| Niederschlag vorige Stunde | `sensor.<name>_precipitation_previous_hour` | mm | stündlich | [RADOLAN](radolan.md) |
| Niederschlag letzte 24h | `sensor.<name>_precipitation_last_24h` | mm | stündlich | [RADOLAN](radolan.md) |
| Niederschlag gestern | `sensor.<name>_precipitation_yesterday` | mm | täglich | [RADOLAN](radolan.md) |
| Niederschlag gesamt | `sensor.<name>_precipitation_total` | mm | stündlich | [Laufende Summen](totals.md) |
| Niederschlag gesamt täglich¹ | `sensor.<name>_precipitation_total_daily` | mm | täglich | [Laufende Summen](totals.md) |
| Zeitraum ohne Niederschlag | `sensor.<name>_timespan_without_precipitation` | d | 5 oder 10 min | [Zeitraum ohne Niederschlag](dry-streak.md) |
| Regenereignisse² | `sensor.<name>_rain_events` | Zustand | 5 min | [Regenereignisse](rain-events.md) |
| Regenwarnung³ | `binary_sensor.<name>_<warnung>_rain_warning` | an/aus | 5 min | [Regenwarnungen](rain-warnings.md) |
| Regenwarnung Status³ | `sensor.<name>_<warnung>_rain_warning_status` | Zustand | 5 min | [Regenwarnungen](rain-warnings.md) |

¹ Bei Installationen, die ab 2026.11.0 eingerichtet wurden, standardmäßig
deaktiviert.
² Nur mit eingeschalteter Option *Sensor „Regenereignisse“ hinzufügen*.
³ Ein Paar pro Regenwarnung, die du hinzufügst, auf einem eigenen Gerät.

## Nur Radar oder angeeicht {#radar-only-or-gauge-adjusted}

- Die Werte von **RADVOR** (RS, RV) und **HymecNG** stammen allein vom Radar.
  Sie werden alle 5 Minuten aktualisiert, und die Vorhersagen reichen zwei
  Stunden voraus.
- Die Werte von **RADOLAN** (`Niederschlag vorige Stunde`, `letzte 24h`,
  `gestern` und die laufenden Summen) sind die Radaranalyse des DWD, mit
  Messungen von Niederschlagsmessern am Boden angeeicht. Sie kommen etwa
  30 Minuten später, sind aber genauer.

Deshalb können `Niederschlag letzte 60 min` und `Niederschlag vorige Stunde`
selbst für dieselbe Stunde voneinander abweichen. Siehe
[Die DWD-Produkte](../how-it-works/dwd-products.md).

## unknown und unavailable {#unknown-and-unavailable}

- **`unknown`** („Unbekannt“): Die Datei des DWD hat keinen Wert für deinen
  Standort (zum Beispiel während eines Radarausfalls), oder es gibt nichts zu
  melden, etwa bei `Niederschlagsbeginn`, wenn kein Regen vorhergesagt ist.
- **`unavailable`** („Nicht verfügbar“): Die Integration hat für dieses
  Produkt keine aktuelle Datei, weil der DWD sie nicht rechtzeitig
  veröffentlicht hat oder sie nicht heruntergeladen werden konnte.

[Verfügbarkeit und Aktualität](../how-it-works/availability.md) erklärt beides
im Detail.
