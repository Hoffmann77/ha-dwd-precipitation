---
title: Regenereignisse
description: Der Sensor Regenereignisse verfolgt jeden Regenschauer von der Vorhersage bis zur Messung, für Blueprints.
---

Der Sensor **Regenereignisse** (`sensor.<name>_rain_events`) ist für
Blueprints gedacht, die vor kurzen Regenschauern warnen oder über sie
berichten. Er verfolgt jedes Ereignis unter einer ID, von der ersten
Vorhersage, die es zeigt, bis es gefallen ist, und meldet, was vorhergesagt
und was gemessen wurde.

Er ist standardmäßig aus. Schalte ihn mit der erweiterten Option
[*Regenereignisse verfolgen*](../getting-started/configuration.md#track-rain-events)
ein. Ist sie an, ruft die Integration außerdem Radaranalysen ab, die sie
verpasst hat, und speichert eine kleine Aufzeichnung des jüngsten Regens auf
der Festplatte; Ausschalten entfernt den Sensor und diese Aufzeichnung.

## Zustand {#state}

| Zustand | Bedeutung |
|---------|-----------|
| `ongoing` („Laufend“) | ein Regenereignis fällt gerade |
| `upcoming` („Bevorstehend“) | gerade fällt keines, aber eines ist innerhalb von zwei Stunden vorhergesagt |
| `none` („Keines“) | beides nicht (ein `unseen`-Ereignis allein zählt ebenfalls als `none`) |

Ein Blueprint kann auf den Zustand triggern und die Details aus den Attributen
lesen. Schlägt die Ereignisverfolgung fehl, fehlen die Attribute, und der
Zustand ist `unknown` („Unbekannt“) statt einer Vermutung.

## Was als Regen zählt {#what-counts-as-rain}

Der Sensor wendet einen einzigen Schwellwert an, die erweiterte Option
[*Schwelle für Regenereignisse*](../getting-started/configuration.md#rain-event-threshold)
(Standard 0,1 mm/h): ein 5-Minuten-Schritt ist nass, wenn seine Menge über
einem Zwölftel davon liegt. Warnstufen sind Sache des Blueprints.

Eine Änderung des Schwellwerts beginnt die Ereignisse mit neuen IDs von vorn;
die gemessenen Schritte und `last_ended` bleiben erhalten.

## Attribute {#attributes}

Die Attribute sind ein Vertrag mit Blueprints, versioniert über `schema`.
Keines davon wird im Verlauf aufgezeichnet.

```yaml
schema: 1                              # prüfe das; es ändert sich nur bei einer inkompatiblen Änderung
base: "2026-10-12T14:30:00+00:00"      # T, der Termin der Veröffentlichung (= forecast_5min[0].end
                                       #   des Binärsensors Niederschlag erwartet)
wet_step_mm: 0.008                     # ein Schritt ist nass oberhalb dieses Werts (mm pro 5 min)
steps_start: "2026-10-12T13:30:00+00:00"
steps: [0.0, …, 1.5, …]                # 36 Werte, mm pro 5 min: 12 gemessene bis T,
                                       # dann forecast_5min[1..24]; null = unbekannt
history_complete: true                 # kein null unter den 12 gemessenen Schritten
events:                                # upcoming | ongoing | unseen, nach Beginn sortiert
  - id: "20261012t1405-0"              # ohne feste Bedeutung, stabil, nie wiederverwendet
    status: ongoing
    first_seen: "…"                    # T der ersten Veröffentlichung, die es zeigte
    start: "…"                         # Beginn des ersten nassen Schritts
    start_clipped: false               # kann früher begonnen haben (davor keine Daten)
    end: "…"                           # Ende des letzten nassen Schritts, vorhergesagt, solange laufend
    beyond_horizon: false              # true: am 2-h-Horizont regnet es noch
    last_wet_observed: "…"             # null, solange bevorstehend
    missing_steps: 0                   # gemessene Schritte ohne Daten innerhalb des Ereignisses
    observed_complete: true            # false: gemessene Mengen können zu niedrig sein
    observed: {mm, peak_1h: {mm, start, end}, peak_10min: {mm, start, end}}
    forecast: {mm, peak_1h, peak_10min}
    total:    {mm, peak_1h, peak_10min}
    forecast_at_onset: {base, start, end, mm, peak_1h, peak_10min,
                        expected_so_far_mm, observed_so_far_mm}   # oder null
    absorbed: []                       # IDs, die in diesem Ereignis aufgegangen sind
last_ended: {id, first_seen, start, start_clipped, end, end_clipped, missing_steps,
             observed_complete, observed, forecast_at_onset, absorbed}   # oder null
```

### Schritte {#steps}

`steps[i]` umfasst 5 Minuten ab `steps_start + 5·i min`: 12 gemessene
Schritte bis zum Termin `base`, dann die 24 Vorhersageschritte. Der gemessene
Teil ist die Radaranalyse des DWD aus jeder Veröffentlichung.
Veröffentlichungen, die die Integration verpasst hat, werden später abgerufen
(nur ihre Analyse, ein kleiner Teil der Datei), sodass eine verlorene
Veröffentlichung keine Lücke hinterlässt.

### Ereignisse {#events}

- Zwei trockene Schritte hintereinander beenden ein Ereignis, ein einzelner
  nicht.
- Ein gemessener Schritt ohne Daten teilt kein Ereignis. Sobald er nicht mehr
  abgerufen werden kann, zählt er bei der Entscheidung, ob das Ereignis zu
  Ende ist, als trocken, und bei einem so beendeten Ereignis ist
  `end_clipped` gesetzt. Mehr als 3 Stunden Schritte ohne Daten in Folge
  zählen als trocken.
- Ein Vorhersageschritt ohne Daten zählt als trocken.
- Ein bevorstehendes Ereignis, das eine Veröffentlichung nicht zeigt, bleibt
  für diese Veröffentlichung als `unseen` erhalten.
- Wachsen mehrere Ereignisse zusammen, behält das am frühesten gesehene seine
  ID und führt die anderen in `absorbed` auf. Teilt sich eines, bekommt der
  spätere Teil eine neue ID.
- Eine ID, die verschwindet, wurde zusammengeführt, wenn sie in einem
  `absorbed` steht, ist beendet, wenn sie `last_ended.id` ist, und sonst
  verschwunden.

### Mengen {#amounts}

- `observed` umfasst die gemessenen Schritte des Ereignisses, `forecast` seine
  Vorhersageschritte innerhalb des Zwei-Stunden-Horizonts, `total` beide.
- `peak_1h` ist die nasseste Stunde, `peak_10min` die nassesten zwei Schritte.
- `total.peak_1h` ist die nasseste Stunde von `steps`, die das Ereignis
  überlappt, *einschließlich* Regen knapp außerhalb davon, weil das
  Starkregenkriterium des DWD einfach die Menge innerhalb einer Stunde ist.

### Vorhersage bei Beginn {#forecast-at-onset}

`forecast_at_onset` ist die letzte Vorhersage des Ereignisses, bevor sein Regen
ankam, eingefroren in dem Moment, in dem er ankam. `expected_so_far_mm` und
`observed_so_far_mm` umfassen seitdem genau dieselben Schritte, für einen
direkten Vergleich wie „9 mm gemessen, wo 3 mm erwartet waren“. Für Regen, der
nie vorhergesagt war, ist es `null`.

### last_ended {#last_ended}

`last_ended` ist das zuletzt abgeschlossene Ereignis, mit eingefrorenen
Messwerten. Es bleibt, bis das nächste Ereignis endet; ein Blueprint für
Berichte muss es daher kopieren, wenn er zum ersten Mal eine neue ID sieht.

## Gut zu wissen {#good-to-know}

- Die Mengen sind reine Radarwerte, gemessene wie vorhergesagte, daher springt
  nichts beim Übergang zu „jetzt“. Sie weichen von einem Niederschlagsmesser
  und von den angeeichten Sensoren wie `Niederschlag gesamt` ab.
- Verpasste Veröffentlichungen können bis zu einer Stunde zurück abgerufen
  werden. Nach einer längeren Zeit, in der Home Assistant nicht lief, oder
  solange der DWD eine Veröffentlichung nicht ausliefert, können die
  gemessenen Werte eines Ereignisses zu niedrig sein: prüfe
  `observed_complete` (und `missing_steps`, `start_clipped`, `end_clipped`).
  Kurz gesagt: starte Home Assistant nicht während eines heftigen
  Wolkenbruchs neu.
- Die Aufzeichnung übersteht Neustarts und Optionsänderungen. Wenn du den
  Konfigurationseintrag der Integration löschst, wird sie mitgelöscht.
- [ADR 0006](/development/adr/0006-rain-events-opt-in-entity) erklärt, warum
  die Ereignisse eine eigene, optional zuschaltbare Entität sind und bei jeder
  Veröffentlichung neu berechnet werden.
