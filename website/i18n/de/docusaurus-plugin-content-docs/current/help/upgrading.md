---
title: Aktualisieren
description: Was sich beim Aktualisieren von DWD Precipitation ändert, einschließlich der in 2026.11.0 umbenannten Entitäten.
---

Jede Version ist in den
[Versionshinweisen auf GitHub](https://github.com/Hoffmann77/ha-dwd-precipitation/releases)
beschrieben. Diese Seite behandelt die Änderungen, die deine Aufmerksamkeit
brauchen oder die dich sonst überraschen könnten.

## 2026.11.0 {#2026110}

### Umbenannte Entitäten {#renamed-entities}

Die Namen der Entitäten geben das Zeitfenster, das sie abdecken, jetzt
einheitlich an (siehe
[Die Namen lesen](../entities/overview.md#reading-the-names)). Installationen,
die vor 2026.11.0 eingerichtet wurden, behalten ihre Entitäts-IDs; nur die
Namen haben sich geändert, deine Automationen, Skripte und Dashboards
funktionieren also weiter. Neue Installationen bekommen die neuen IDs:

| Neuer Name | ID bei Installationen von vor 2026.11.0 | ID bei neuen Installationen |
|------------|-----------------------------------------|-----------------------------|
| Niederschlag letzte 60 min | `sensor.<name>_precipitation_now` | `sensor.<name>_precipitation_last_60_min` |
| Niederschlag nächste 60 min | `sensor.<name>_precipitation_next_1h` | `sensor.<name>_precipitation_next_60_min` |
| Niederschlag nächste 60–120 min | `sensor.<name>_precipitation_next_1_2h` | `sensor.<name>_precipitation_next_60_120_min` |
| Maximaler Stundenniederschlag nächste 120 min | `sensor.<name>_peak_hourly_precipitation_next_2h` | `sensor.<name>_peak_hourly_precipitation_next_120_min` |
| Spitzenintensität nächste 60 min | `sensor.<name>_peak_intensity_next_1h` | `sensor.<name>_peak_intensity_next_60_min` |
| Spitzenintensität nächste 60–120 min | `sensor.<name>_peak_intensity_next_1_2h` | `sensor.<name>_peak_intensity_next_60_120_min` |
| Niederschlagsart aktuell | `sensor.<name>_precipitation_type` | `sensor.<name>_precipitation_type_now` |
| Niederschlag vorige Stunde | `sensor.<name>_precipitation_last_1h` | `sensor.<name>_precipitation_previous_hour` |
| Niederschlag gesamt | `sensor.<name>_precipitation_total_hourly` | `sensor.<name>_precipitation_total` |

Die IDs sind in jeder Sprache gleich, denn Home Assistant bildet sie aus den
englischen Namen. Alle anderen Entitäten haben ihre Namen und ihre IDs
behalten.

Wenn du die neuen IDs auch bei einer älteren Installation möchtest, benenne
die Entitäten in ihren Einstellungen um (oder nutze **Entitäts-IDs neu
erstellen** auf der Geräteseite) und passe deine Automationen, Skripte und
Dashboards entsprechend an. Keine neue ID wurde von einer älteren Version an
eine andere Entität vergeben, es gibt also keine Konflikte.

### Neue Entitäten {#new-entities}

- **Niederschlagsintensität aktuell** (mm/h): die aktuelle Regenrate. Siehe
  [RADVOR RV](../entities/radvor-rv.md#precipitation-intensity-now).
- **Niederschlag nächste 120 min** (mm): die Vorhersagesumme für die ganzen
  zwei Stunden. Siehe
  [RADVOR RS](../entities/radvor-rs.md#precipitation-next-120-min).
- **Spitzenintensität nächste 120 min** (mm/h): die stärkste Rate in den
  nächsten zwei Stunden. Siehe
  [RADVOR RV](../entities/radvor-rv.md#peak-intensities).
- **Regenereignisse**, einzuschalten mit der erweiterten Option
  *Regenereignisse verfolgen*. Siehe
  [Regenereignisse](../entities/rain-events.md).

### Niederschlag vorige Stunde ist eine volle Stunde {#precipitation-previous-hour-is-a-clock-hour}

`Niederschlag vorige Stunde` (früher *Precipitation last 1h*) war bisher die
Stunde bis :50. Jetzt ist es die letzte volle Stunde, etwa 11:00–12:00, die zu
den Stundenstatistiken von Home Assistant passt. Der Wert kommt etwa
28 Minuten nach der vollen Stunde.

`Niederschlag gesamt` wechselt mit auf volle Stunden. Eine aus einer älteren
Version übernommene Summe wechselt bei ihrer ersten Aktualisierung und lässt
dabei die 10 Minuten dazwischen einmal aus, statt 50 Minuten doppelt zu
zählen. Siehe [ADR 0002](/development/adr/0002-rw-reads-the-clock-hour).

### Zeitraum ohne Niederschlag: Wahl der Quelle {#timespan-without-precipitation-choice-of-source}

Die neue Option *Produkt, das den Trockenzähler zurücksetzt* wählt zwischen
der angeeichten Stunde des DWD (RW) und `Niederschlag letzte 60 min` (RS).
Neue Installationen nutzen RW; **bestehende Installationen behalten RS**, ein
Update ändert also nichts. Wenn du RW bevorzugst, stelle es in den Optionen
um; der Zähler behält dabei seinen Wert. Siehe
[Zeitraum ohne Niederschlag](../entities/dry-streak.md).

### Niederschlag gesamt täglich bei neuen Installationen deaktiviert {#precipitation-total-daily-disabled-on-new-installs}

`Niederschlag gesamt täglich` zählt den Regen jedes Tages in den Statistiken
erst am Folgetag, deshalb ist der Sensor bei neuen Installationen
deaktiviert; `Niederschlag gesamt` ist der, den du verwenden solltest.
**Installationen, die ihn schon hatten, behalten ihn aktiviert.** Siehe
[Laufende Summen](../entities/totals.md#precipitation-total-daily).
