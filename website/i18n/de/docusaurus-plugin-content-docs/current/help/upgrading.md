---
title: Aktualisieren
description: Was sich beim Aktualisieren von DWD Precipitation ändert, einschließlich der in 2026.11.0 umbenannten Entitäten.
---

Jede Version ist in den
[Versionshinweisen auf GitHub](https://github.com/Hoffmann77/ha-dwd-precipitation/releases)
beschrieben. Diese Seite fasst die Änderungen zusammen, die Aufmerksamkeit brauchen oder
sonst überraschen könnten.

## 2026.11.0

### Umbenannte Entitäten

Die Namen der Entitäten geben das Zeitfenster jetzt einheitlich an. Installationen,
die vor 2026.11.0 eingerichtet wurden, behalten ihre Entitäts-IDs; nur die
Namen haben sich geändert, Automationen, Skripte und Dashboards
funktionieren also weiter. Neue Installationen bekommen die neuen IDs:

| Neuer Name | ID bei Installationen vor 2026.11.0 | ID bei neuen Installationen |
|------------|-------------------------------------|-----------------------------|
| Niederschlag letzte 60 min | `sensor.<name>_precipitation_now` | `sensor.<name>_precipitation_last_60_min` |
| Niederschlag nächste 60 min | `sensor.<name>_precipitation_next_1h` | `sensor.<name>_precipitation_next_60_min` |
| Niederschlag nächste 60–120 min | `sensor.<name>_precipitation_next_1_2h` | `sensor.<name>_precipitation_next_60_120_min` |
| Maximaler Stundenniederschlag nächste 120 min | `sensor.<name>_peak_hourly_precipitation_next_2h` | `sensor.<name>_peak_hourly_precipitation_next_120_min` |
| Spitzenintensität nächste 60 min | `sensor.<name>_peak_intensity_next_1h` | `sensor.<name>_peak_intensity_next_60_min` |
| Spitzenintensität nächste 60–120 min | `sensor.<name>_peak_intensity_next_1_2h` | `sensor.<name>_peak_intensity_next_60_120_min` |
| Niederschlagsart aktuell | `sensor.<name>_precipitation_type` | `sensor.<name>_precipitation_type_now` |
| Niederschlag vorige Stunde | `sensor.<name>_precipitation_last_1h` | `sensor.<name>_precipitation_previous_hour` |
| Niederschlag gesamt | `sensor.<name>_precipitation_total_hourly` | `sensor.<name>_precipitation_total` |

Die IDs sind in jeder Sprache gleich, denn Home Assistant bildet sie aus dem
englischen Namen. Alle anderen Entitäten haben Namen und IDs behalten.

Wer die neuen IDs auch bei einer älteren Installation möchte, benennt die
Entitäten in ihren Einstellungen um (oder nutzt **Entitäts-IDs neu erstellen**
auf der Geräteseite) und passt Automationen, Skripte und Dashboards an. Keine
neue ID wurde von einer älteren Version an eine andere Entität vergeben, es gibt
also keine Konflikte.

### Neue Entitäten

- **Niederschlagsintensität aktuell** (mm/h): die aktuelle Regenrate.
- **Niederschlag nächste 120 min** (mm): die Vorhersage für die ganzen zwei
  Stunden.
- **Spitzenintensität nächste 120 min** (mm/h): die stärkste Rate in den
  nächsten zwei Stunden.
- **Regenereignisse**, einzuschalten mit der erweiterten Option
  *Regenereignisse verfolgen*.

### Niederschlag vorige Stunde ist eine Uhrzeitstunde

`Niederschlag vorige Stunde` (vorher *Precipitation last 1h*) war die Stunde
bis :50. Jetzt ist es die letzte volle Uhrzeitstunde, etwa 11:00–12:00, die
zu den Stundenstatistiken von Home Assistant passt. Der Wert kommt etwa 28
Minuten nach der vollen Stunde.

`Niederschlag gesamt` wechselt mit auf volle Stunden. Eine aus einer älteren
Version übernommene Summe wechselt bei ihrer ersten Aktualisierung und lässt
dabei die 10 Minuten dazwischen einmal aus, statt 50 Minuten doppelt zu zählen.
Siehe [ADR 0002](/development/adr/0002-rw-reads-the-clock-hour).

### Zeitraum ohne Niederschlag: Wahl der Quelle

Die neue Option *Produkt, das den Trockenzähler zurücksetzt* wählt zwischen
der an Messstationen angeeichten Stunde des DWD (RW) und
`Niederschlag letzte 60 min` (RS). Neue Installationen nutzen RW;
**bestehende Installationen behalten RS**, ein Update ändert also nichts. Wer
RW bevorzugt, stellt es in den Optionen um; der Zähler behält dabei seinen
Wert.

### Niederschlag gesamt täglich bei neuen Installationen deaktiviert

`Niederschlag gesamt täglich` zählt den Regen jedes Tages in der Statistik erst
am Folgetag, deshalb ist der Sensor bei neuen Installationen deaktiviert;
`Niederschlag gesamt` ist der richtige für Statistiken. **Installationen, die
ihn schon hatten, behalten ihn aktiviert.**
