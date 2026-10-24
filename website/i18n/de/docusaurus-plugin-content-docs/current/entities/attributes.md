---
title: Attribute
description: Die Attribute der Entitäten von DWD Precipitation, und die Option für technische Details.
---

## Immer vorhanden {#always-present}

| Attribut | Entitäten | Beschreibung |
|----------|-----------|--------------|
| `minutes_until` / `at` | `Niederschlagsbeginn`, `Niederschlagsende`, `Niederschlag erwartet` | Die Form, die *nicht* als Zustand angezeigt wird: ganze Minuten bis zum Ereignis oder dessen Zeitpunkt in ISO-8601 UTC. Der Binärsensor hat beide; sie zeigen auf den vorhergesagten Beginn (`null`, wenn kein Regen erwartet wird) |
| `forecast_5min` | `Niederschlag erwartet` | Die vollständige RV-Vorhersage mit 25 Schritten (0 bis 120 min in 5-Minuten-Schritten); jeder Schritt hat `lead` (Minuten ab dem Termin der Veröffentlichung), `start`, `end`, `value` (mm in diesen 5 Minuten) und `intensity` (mm/h). `value` und `intensity` sind `null` für einen Schritt ohne Daten |
| `window_start` / `window_end` | `Niederschlagsintensität aktuell` | Beginn und Ende der 5-Minuten-Radaranalyse, aus der die Rate stammt |
| `amount_5min` | `Niederschlagsintensität aktuell` | Der Regen in diesem Fenster in mm, bevor er in mm/h umgerechnet wird; `null` ohne Daten |
| `window_start` / `window_end` | `Maximaler Stundenniederschlag nächste 120 min` | Beginn und Ende der nassesten Stunde; `null`, wenn kein Regen vorhergesagt ist. Bei zwei gleichen Fenstern das frühere |
| `forecast_rolling_1h` | `Maximaler Stundenniederschlag nächste 120 min` | Die stündliche Reihe, aus der der Sensor seinen Wert wählt, siehe [die Reihe der gleitenden Stunden](radvor-rv.md#the-rolling-hour-series) |
| `hours_without_precipitation` | `Zeitraum ohne Niederschlag` | Die Trockenphase in Stunden; `null`, bis der Zähler gestartet ist |
| `dry_since` | `Zeitraum ohne Niederschlag` | Der Zeitpunkt, ab dem der Zähler zählt: das Ende der Stunde, die ihn zuletzt zurückgesetzt hat, oder bei einer neuen Installation der Beginn der Trockenphase, die die Daten des DWD zeigen |
| `counted_until` | `Niederschlag gesamt`, `Niederschlag gesamt täglich` | Ende des neuesten DWD-Fensters, das in der Summe enthalten ist; `null`, bis die erste Datei eintrifft. Verpasste Dateien, die später geholt werden, werden nachträglich addiert, ohne es zurückzusetzen |
| `schema`, `events`, `steps`, … | `Regenereignisse` | Der Regen rund um deinen Standort, in Ereignisse aufgeteilt, siehe [Regenereignisse](rain-events.md#attributes) |
| `event_id`, `start`, `mm`, `peak_1h`, `peak_10min`, `type` | `Regenwarnung Status` | Das Regenereignis, um das es der Warnung geht; alle `null`, solange es trocken ist, siehe [Regenwarnungen](rain-warnings.md#attributes) |

Zeiten sind ISO-8601 in UTC, zum Beispiel `2026-10-12T14:30:00+00:00`;
Templates wandeln sie mit `as_local(as_datetime(...))` in Ortszeit um.

## Nicht im Verlauf aufgezeichnet {#not-recorded-in-history}

Einige Attribute sind groß und ändern sich alle 5 Minuten, deshalb lässt der
Recorder von Home Assistant sie aus der Verlaufsdatenbank heraus:
`forecast_5min`, `forecast_rolling_1h`, `window_start` / `window_end` und
jedes Attribut von `Regenereignisse` und `Regenwarnung Status`. Am aktuellen Zustand sind sie immer
verfügbar, sodass Templates, Automationen und Blueprints sie lesen können; nur
der Verlaufsgraph speichert sie nicht.

## Technische Details {#technical-details}

Mit eingeschalteter Option
[*Technische Details zu den Sensoren hinzufügen*](../getting-started/configuration.md#technical-details)
hat jeder DWD-Sensor außer `Niederschlag erwartet`, den beiden laufenden
Summen, `Zeitraum ohne Niederschlag`, `Regenereignisse` und den
Regenwarnungen zusätzlich:

| Attribut | Beschreibung |
|----------|--------------|
| `source_product` | DWD-Produktkennung aus dem Dateikopf (z. B. `"RS_top_view"`, `"RV"`, `"RW"`) |
| `source_timestamp` | UTC-Bezugszeit der DWD-Datei. Bei RADVOR die Analysezeit vor der Vorlaufzeit der Vorhersage; bei RADOLAN das Ende des Messfensters |
| `lead_time_minutes` | Vorlaufzeit der Vorhersage in Minuten: `0`, `60` oder `120` bei RADVOR, das Ende der nassesten Stunde bei `Maximaler Stundenniederschlag nächste 120 min` (dort `null`, wenn kein Regen vorhergesagt ist), `null` bei `Niederschlagsbeginn` und `Niederschlagsende`, HymecNG und RADOLAN |
| `data_start` / `data_end` | Beginn und Ende des Zeitraums, den der Wert abdeckt, ISO-8601 UTC (bei `Maximaler Stundenniederschlag nächste 120 min` die nasseste Stunde, also dasselbe wie `window_start` / `window_end`); fehlt bei Werten ohne Zeitraum |

Sie sind in Templates nützlich und wenn du ein Problem meldest, denn sie sagen
genau, aus welcher DWD-Datei ein Wert stammt.
