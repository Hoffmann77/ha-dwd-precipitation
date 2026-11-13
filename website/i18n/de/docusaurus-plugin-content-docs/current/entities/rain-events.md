---
title: Regenereignisse
description: Der Sensor Regenereignisse verfolgt jeden Schauer an deinem Standort, von der ersten Vorhersage, die ihn zeigt, bis er vorbei ist.
---

Der Sensor **Regenereignisse** (`sensor.<name>_rain_events`) verfolgt jeden
Schauer an deinem Standort als ein *Regenereignis*: von der ersten
Vorhersage, die ihn zeigt, über die Zeit, in der er fällt, bis er vorbei ist.
Zu jedem Ereignis sagt er dir, wann es beginnt und endet, wie viel Regen
vorhergesagt ist, wie viel tatsächlich gefallen ist und ob es Regen, Schnee
oder Hagel ist.

Er ist für Blueprints und Automationen gedacht, die vor Regen warnen oder
hinterher über ihn berichten, etwa „Starker Schauer in 20 Minuten, 8 mm
erwartet“ oder „Der Schauer brachte 12 mm, 3 mm mehr als vorhergesagt“.

:::tip Nur eine Warnung?

Für eine einfache Warnung wie „Wäsche, 60 Minuten vorher“ brauchst du weder
diesen Sensor noch einen Blueprint: Füge eine
[Regenwarnung](rain-warnings.md) hinzu. Sie arbeitet mit denselben
Regenereignissen und gibt dir eine einfache An/Aus-Entität.

:::

## Einschalten {#turning-it-on}

Der Sensor ist standardmäßig aus. Schalte ihn in den Optionen im Abschnitt
*Regenereignisse und Regenwarnungen* mit
[*Sensor „Regenereignisse“ hinzufügen*](../getting-started/configuration.md#track-rain-events)
ein.

Solange er an ist, speichert die Integration eine kleine Aufzeichnung des
jüngsten Regens auf der Festplatte und lädt Radardaten nach, die sie verpasst
hat (etwa während eines Neustarts von Home Assistant), damit die Mengen eines
Ereignisses keine Lücken haben. Ausschalten entfernt den Sensor; die
Aufzeichnung wird ebenfalls gelöscht, sofern keine Regenwarnung sie noch
nutzt.

## So funktioniert es {#how-it-works}

### Fünf-Minuten-Schritte {#steps}

Das Radar des DWD misst den Regen alle 5 Minuten und sagt ihn zwei Stunden
voraus, ebenfalls in 5-Minuten-Schritten. Die Integration setzt beides für
deinen Standort zu einer Zeitleiste zusammen: die **letzte Stunde, wie sie
gemessen wurde** (12 Schritte), und die **nächsten zwei Stunden, wie sie
vorhergesagt sind** (24 Schritte).

Alle 5 Minuten veröffentlicht der DWD eine neue Aktualisierung, hier
*Veröffentlichung* genannt. Mit jeder Veröffentlichung fällt der älteste
gemessene Schritt heraus, der gerade zu Ende gegangene Schritt wird gemessen,
und die Vorhersage rückt um 5 Minuten weiter.

### Was als Regen zählt {#what-counts-as-rain}

Ein Schritt gilt als nass, wenn er mehr Regen hat, als die Option
[*Nur Regen zählen, der stärker ist als*](../getting-started/configuration.md#rain-event-threshold)
im Abschnitt *Regenereignisse und Regenwarnungen* zulässt. Der Standard ist
0,1 mm/h; das lässt alles außer der schwächsten Spur durch. Die Option ist
eine Intensität pro Stunde; für einen 5-Minuten-Schritt wird sie durch 12
geteilt (das Attribut `wet_step_mm` zeigt das Ergebnis).

Mit [*Umgebung des Standorts auswerten*](../getting-started/configuration.md#neighbourhood)
(Standard: an) ist der Regen eines Schritts die nasseste Zelle im Umkreis von
etwa 1,5 km, solange die Vorhersage den Regen auf den Standort zu bewegt, und
sonst der der eigenen Zelle (`event_value` in `forecast_5min`). Ein nach
einem Neustart nachgeholter gemessener Schritt ist immer der der eigenen
Zelle.

Eine Änderung dieser Einstellung beginnt die Ereignisse von vorn, mit neuen
IDs. Die gemessenen Schritte und `last_ended` bleiben erhalten.

Der Sensor selbst hat keine Warnstufen: Ob 2 mm eine Nachricht wert sind,
entscheidet dein Blueprint oder die Mindestwerte einer
[Regenwarnung](rain-warnings.md).

### Von der Vorhersage zur Messung {#events}

Nasse Schritte, die aufeinander folgen, bilden ein Regenereignis. Ein
Ereignis durchläuft diese Stufen:

1. **upcoming** („Bevorstehend“): Die Vorhersage zeigt Regen, gefallen ist
   aber noch keiner. Das Ereignis bekommt eine ID, die es behält, bis es
   vorbei ist.
2. **ongoing** („Laufend“): Das Radar hat seinen ersten Regen gemessen. Ab
   jetzt hat das Ereignis neben vorhergesagten auch gemessene Mengen und eine
   Niederschlagsart.
3. **beendet:** Auf seinen letzten Regen folgen zwei gemessene trockene
   Schritte hintereinander (10 Minuten). Das Ereignis wandert mit seinen
   endgültigen Mengen nach `last_ended`.

Ein einzelner trockener Schritt dazwischen beendet kein Ereignis: Eine kurze
Pause in einem Schauer gehört noch zum selben Schauer.

Vorhersagen ändern sich von einer Veröffentlichung zur nächsten, und die
Ereignisse folgen ihnen:

- **Eine Vorhersage verliert einen Schauer.** Vorhersagen lassen einen
  kleinen Schauer oft für eine Veröffentlichung fallen und finden ihn in der
  nächsten wieder. Ein bevorstehendes Ereignis, das die neueste Vorhersage
  nicht zeigt, bleibt für eine Veröffentlichung als `unseen` erhalten; zeigt
  die nächste Vorhersage es wieder, geht es unter seiner ID weiter, sonst ist
  es weg.
- **Zwei Schauer wachsen zusammen.** Das Ereignis, das zuerst gesehen wurde,
  behält seine ID und führt die anderen in `absorbed` auf.
- **Ein Schauer teilt sich.** Der frühere Teil behält die ID, der spätere
  wird ein neues Ereignis.
- **Fehlende Daten.** Ein gemessener Schritt ohne Daten (der DWD hat ihn
  nicht geliefert, oder Home Assistant lief nicht) beendet oder teilt kein
  Ereignis, denn es könnte geregnet haben. Lässt sich der Schritt auch später
  nicht abrufen, zählt er als trocken, sobald er die letzte Stunde verlassen
  hat, und bei einem so beendeten Ereignis ist `end_clipped` gesetzt. Mehr
  als 3 Stunden Schritte ohne Daten in Folge zählen als trocken. Ein
  Vorhersageschritt ohne Daten zählt als trocken.

Verschwindet also eine ID aus `events`, wurde sie zusammengeführt, wenn sie
im `absorbed` eines Ereignisses steht, ist beendet, wenn sie `last_ended.id`
ist, und wurde sonst von der Vorhersage fallen gelassen.

### Ein Beispiel {#an-example}

Um 14:00 zeigt die Vorhersage einen Schauer von 14:35 bis 15:05. Die Zeiten
links sind Veröffentlichungen; jede erreicht Home Assistant ein paar Minuten
später, wenn der DWD sie veröffentlicht hat (siehe
[Veröffentlichungszeitpunkte](../how-it-works/release-timing.md)).

| Veröffentlichung | Was passiert | Zustand |
|------------------|--------------|---------|
| 14:00 | Das Ereignis erscheint, mit `start` 14:35, `end` 15:05 und einer Vorhersage von 3 mm. | `upcoming` |
| 14:10 | Eine neuere Vorhersage verschiebt es auf 14:40. Gleiche ID, neue Zeiten. | `upcoming` |
| 14:45 | Das Radar hat von 14:40 bis 14:45 Regen gemessen: den ersten Regen. Die Vorhersage der Veröffentlichung davor (14:40) wird als `forecast_at_onset` aufbewahrt. | `ongoing` |
| 15:00 | Bisher sind 4,2 mm gefallen (`observed.mm`), 0,8 mm mehr sind vorhergesagt (`forecast.mm`). | `ongoing` |
| 15:20 | Der letzte Regen endete um 15:10, und die zwei Schritte danach waren trocken. Das Ereignis wandert nach `last_ended`. | `none` |

## Zustand {#state}

| Zustand | Bedeutung |
|---------|-----------|
| `ongoing` („Laufend“) | ein Regenereignis fällt gerade |
| `upcoming` („Bevorstehend“) | gerade fällt keines, aber eines ist innerhalb von zwei Stunden vorhergesagt |
| `none` („Keines“) | beides nicht (ein `unseen`-Ereignis allein zählt ebenfalls als `none`) |

Eine Automation kann auf den Zustand triggern und die Details aus den
Attributen lesen. Schlägt die Ereignisverfolgung fehl, fehlen die Attribute,
und der Zustand ist `unknown` („Unbekannt“) statt einer Vermutung.

## Attribute {#attributes}

Die Attribute enthalten die Details. Sie sind für Blueprints und Templates
gedacht und ein fester Vertrag: Ihre Namen und ihre Bedeutung ändern sich nur
mit einer neuen `schema`-Nummer. Keines davon wird im Verlauf aufgezeichnet,
sie füllen also deine Datenbank nicht.

Alle Zeiten sind in UTC, im ISO-Format wie `2026-10-12T14:30:00+00:00`; in
einem Template macht `as_local(as_datetime(...))` daraus deine Ortszeit. Alle
Mengen sind in mm.

So sehen die Attribute im Beispiel oben um 15:00 aus:

```yaml
schema: 1
base: "2026-10-12T15:00:00+00:00"
wet_step_mm: 0.008
steps_start: "2026-10-12T14:00:00+00:00"
steps: [0.0, 0.0, …, 0.6, 0.9, …, 0.3, 0.0, …]   # 36 Werte
history_complete: true
events:
  - id: "20261012t1400-0"
    status: ongoing
    first_seen: "2026-10-12T14:00:00+00:00"
    start: "2026-10-12T14:40:00+00:00"
    start_clipped: false
    end: "2026-10-12T15:10:00+00:00"
    beyond_horizon: false
    last_wet_observed: "2026-10-12T15:00:00+00:00"
    missing_steps: 0
    observed_complete: true
    observed:
      mm: 4.2
      peak_1h: {mm: 4.2, start: "…14:40…", end: "…15:00…"}
      peak_10min: {mm: 1.5, start: "…14:45…", end: "…14:55…"}
      types: {rain: 4}
    forecast: {mm: 0.8, peak_1h: {…}, peak_10min: {…}}
    total: {mm: 5.0, peak_1h: {…}, peak_10min: {…}}
    type: rain
    forecast_at_onset:
      base: "2026-10-12T14:40:00+00:00"
      start: "2026-10-12T14:40:00+00:00"
      end: "2026-10-12T15:05:00+00:00"
      mm: 3.0
      peak_1h: {…}
      peak_10min: {…}
      expected_so_far_mm: 2.9
      observed_so_far_mm: 4.2
    absorbed: []
last_ended: null
```

### Die Zeitleiste {#the-timeline}

| Attribut | Bedeutung |
|----------|-----------|
| `schema` | Die Version dieses Aufbaus, derzeit `1`. Ein Blueprint sollte sie prüfen: Sie ändert sich nur, wenn sich etwas so ändert, dass Blueprints nicht mehr funktionieren würden. |
| `base` | Der Termin der neuesten Veröffentlichung: das Ende des neuesten gemessenen Schritts und, soweit die Daten reichen, „jetzt“. |
| `wet_step_mm` | Wie viel Regen ein 5-Minuten-Schritt braucht, um als nass zu gelten, aus der Schwellwert-Option (0,1 mm/h ergibt `0.008`). Ein Schritt ist nass *oberhalb* dieses Werts. |
| `steps_start` | Der Beginn des ersten Schritts in `steps`, eine Stunde vor `base`. |
| `steps` | Der Regen jedes 5-Minuten-Schritts in mm: zuerst die 12 gemessenen bis `base`, dann die 24 vorhergesagten. `steps[i]` umfasst die 5 Minuten ab `steps_start` + 5 × i Minuten. `null` heißt: keine Daten für diesen Schritt. Der vorhergesagte Teil ist derselbe wie `forecast_5min` von [`Niederschlag erwartet`](radvor-rv.md#precipitation-expected). |
| `history_complete` | `true`, wenn alle 12 gemessenen Schritte Daten haben. |
| `events` | Die bevorstehenden, laufenden und `unseen`-Ereignisse, das früheste zuerst. Leer, wenn kein Regen in Sicht ist. |
| `last_ended` | Das zuletzt beendete Ereignis oder `null`. Siehe [last_ended](#last_ended). |

### Ein Ereignis {#an-event}

Jeder Eintrag von `events` hat:

| Attribut | Bedeutung |
|----------|-----------|
| `id` | Der Name des Ereignisses, etwa `20261012t1400-0`. Er bleibt das ganze Ereignis über gleich und wird nie für ein anderes verwendet. Nutze ihn nur, um ein Ereignis wiederzuerkennen; lies nichts aus dem Text heraus. |
| `status` | `upcoming`, `ongoing` oder `unseen`, siehe [Von der Vorhersage zur Messung](#events). |
| `first_seen` | Die Veröffentlichung, die das Ereignis zuerst zeigte: wie früh es angekündigt wurde. |
| `start` | Wann sein Regen beginnt: der Beginn seines ersten nassen Schritts. Vorhergesagt, solange es bevorsteht, gemessen, sobald es läuft. |
| `start_clipped` | `true`, wenn der Regen früher als `start` begonnen haben kann, weil die Schritte davor keine Daten haben (etwa nach einem Neustart). |
| `end` | Wann sein Regen endet: das Ende seines letzten nassen Schritts, gemessen oder vorhergesagt. Solange das Ereignis läuft, ist das meist noch eine Vorhersage. |
| `beyond_horizon` | `true`, wenn es am Ende der Vorhersage, zwei Stunden voraus, noch regnet. `end` ist dann nur das Ende der Vorhersage, und der Regen kann länger dauern. |
| `last_wet_observed` | Das Ende des neuesten Schritts, in dem tatsächlich Regen gemessen wurde. `null`, solange es bevorsteht. |
| `missing_steps` | Wie viele gemessene Schritte des Ereignisses keine Daten haben. |
| `observed_complete` | `true`, wenn der gemessene Teil vollständig ist: keine `missing_steps` und kein `start_clipped`. Bei `false` können die gemessenen Mengen zu niedrig sein. |
| `observed` | Der bisher gemessene Regen, siehe [Mengen](#amounts). |
| `forecast` | Der Regen, der für das Ereignis noch vorhergesagt ist, innerhalb der zwei Stunden. |
| `total` | Gemessen und vorhergesagt zusammen: die beste Schätzung für das ganze Ereignis. |
| `type` | Die Niederschlagsart des neuesten gemessenen nassen Schritts, etwa `rain` oder `snow`. `null`, solange es bevorsteht, siehe [Niederschlagsart](#precipitation-type). |
| `forecast_at_onset` | Was die Vorhersage kurz vor dem Regen sagte, siehe [Vorhersage bei Beginn](#forecast-at-onset). `null`, solange es bevorsteht, und für Regen, der nie vorhergesagt war. |
| `absorbed` | Die IDs der Ereignisse, die in diesem aufgegangen sind. |

Ein `unseen`-Ereignis zeigt die Werte, die es in der letzten Vorhersage
hatte, die es noch zeigte.

### Mengen {#amounts}

`observed`, `forecast` und `total` haben jeweils:

| Attribut | Bedeutung |
|----------|-----------|
| `mm` | Die Regenmenge. |
| `peak_1h` | Die nassesten 60 Minuten, als `mm`, `start` und `end`. Bei einem Ereignis unter einer Stunde das ganze Ereignis. |
| `peak_10min` | Die nassesten 10 Minuten (zwei Schritte hintereinander), als `mm`, `start` und `end`. Gut für kurze heftige Güsse. |

`observed` hat außerdem `types`, siehe unten. Ein Spitzenwert ist `null`, wenn
es nichts zu betrachten gibt, etwa `forecast.peak_1h`, sobald aller Regen
gefallen ist.

Zwei Details für Blueprints, die mit Warnstufen vergleichen:

- `total.peak_1h` ist die nasseste Stunde von `steps`, die das Ereignis
  überlappt, *einschließlich* Regen knapp außerhalb davon. Die
  Starkregenwarnungen des DWD beruhen einfach auf der Menge innerhalb einer
  Stunde, daher zählen zwei Schauer kurz hintereinander zusammen.
- Schritte ohne Daten zählen in jeder Menge als 0 mm.

### Niederschlagsart {#precipitation-type}

- `observed.types` zählt die gemessenen nassen Schritte des Ereignisses nach
  Art, so wie die [HymecNG](hymecng.md)-Klassifikation des DWD sie am Ende
  jedes Schritts für deinen Standort angab. Die Arten sind die Zustände von
  [Niederschlagsart aktuell](hymecng.md#precipitation-type-now), etwa
  `rain`, `snow` oder `hail`. `{rain: 9, snow: 3}` heißt 45 Minuten Regen und
  15 Minuten Schnee.
- `type` ist die Art des neuesten gemessenen nassen Schritts, der eine hat.
- Nur gemessene Schritte haben eine Art. Der DWD sagt Mengen voraus, keine
  Arten; ein bevorstehendes Ereignis hat daher `type: null` und keine
  `types`, und seine Art erscheint mit dem ersten gemessenen Regen. Die
  Integration rät keine.
- Die Arten sind die des DWD, unverändert. HymecNG klassifiziert unabhängig
  von den Mengen; ein nasser Schritt kann daher `no_precipitation` oder
  `not_classified` haben und wird unter diesem Zustand gezählt.
- Ein nasser Schritt ohne Art wird nicht gezählt; die Zählungen können daher
  weniger ergeben als die nassen Schritte des Ereignisses. Das passiert, wenn
  HymecNG für deinen Standort keine Daten hat oder seine Datei nicht abgerufen
  werden konnte; eine verpasste Art wird wie verpasste Radardaten später
  abgerufen, solange der Schritt in der letzten Stunde liegt.
- Meist bekommt ein Schritt seine Art, bevor seine Radarmessung ankommt. Eine
  Art, die später ankommt, erscheint ab der nächsten Veröffentlichung.

### Vorhersage bei Beginn {#forecast-at-onset}

`forecast_at_onset` ist die letzte Vorhersage für das Ereignis, bevor sein
Regen ankam, und bleibt ab dann unverändert. Sie beantwortet die Frage „Wovor
wurden wir gewarnt?“:

| Attribut | Bedeutung |
|----------|-----------|
| `base` | Die Veröffentlichung dieser Vorhersage. |
| `start`, `end` | Wann diese Vorhersage Beginn und Ende des Regens erwartete. |
| `mm`, `peak_1h`, `peak_10min` | Die Mengen, die diese Vorhersage erwartete. |
| `expected_so_far_mm` | Was diese Vorhersage für die seitdem gemessenen Schritte erwartete. |
| `observed_so_far_mm` | Was in genau diesen Schritten tatsächlich gefallen ist. |

Die letzten beiden umfassen genau dieselben Schritte (höchstens die zwei
Stunden, die die Vorhersage reichte), vergleichen also Gleiches mit Gleichem:
„9 mm gefallen, wo 3 mm erwartet waren“.

### last_ended {#last_ended}

`last_ended` ist das zuletzt beendete Ereignis, mit seinen endgültigen
Werten: `id`, `first_seen`, `start`, `start_clipped`, `end`,
`missing_steps`, `observed`, `type`, `forecast_at_onset` und `absorbed`, wie
bei einem Ereignis, und zusätzlich:

| Attribut | Bedeutung |
|----------|-----------|
| `end_clipped` | `true`, wenn das Ende durch Schritte ohne Daten entschieden wurde; der Regen kann also länger gedauert haben. |
| `observed_complete` | `true`, wenn nichts fehlt: keine `missing_steps`, kein `start_clipped` und kein `end_clipped`. |

Es hat kein `forecast` und kein `total`: Alles ist gemessen. Es bleibt, bis
das nächste Ereignis endet; ein Blueprint, der über Ereignisse berichtet,
sollte daher handeln, wenn er eine neue `last_ended.id` sieht.

## Template-Beispiele {#template-examples}

Ersetze `sensor.home_rain_events` durch deinen Sensor. Wann der nächste Regen
beginnt, in Ortszeit:

```jinja
{% set events = state_attr('sensor.home_rain_events', 'events') or [] %}
{% set upcoming = events | selectattr('status', 'eq', 'upcoming') | first %}
{{ as_local(as_datetime(upcoming.start)).strftime('%H:%M') if upcoming else 'kein Regen in Sicht' }}
```

Wie viel der aktuelle Schauer insgesamt bringen soll:

```jinja
{% set events = state_attr('sensor.home_rain_events', 'events') or [] %}
{% set now_raining = events | selectattr('status', 'eq', 'ongoing') | first %}
{{ now_raining.total.mm if now_raining else 0 }} mm
```

Wie der letzte Schauer im Vergleich zu seiner Vorhersage ausfiel:

```jinja
{% set last = state_attr('sensor.home_rain_events', 'last_ended') %}
{% if last and last.forecast_at_onset %}
  {{ last.forecast_at_onset.observed_so_far_mm }} mm gefallen,
  {{ last.forecast_at_onset.expected_so_far_mm }} mm waren vorhergesagt.
{% endif %}
```

## Gut zu wissen {#good-to-know}

- Die Mengen sind reine Radarwerte, gemessene wie vorhergesagte, daher springt
  nichts beim Übergang zu „jetzt“. Sie weichen von einem Niederschlagsmesser
  und von den angeeichten Sensoren wie `Niederschlag gesamt` ab.
- Verpasste Radardaten können bis zu einer Stunde zurück abgerufen werden.
  Nach einer längeren Zeit, in der Home Assistant nicht lief, oder solange der
  DWD eine Veröffentlichung nicht ausliefert, können die gemessenen Werte
  eines Ereignisses zu niedrig sein: prüfe `observed_complete` (und
  `missing_steps`, `start_clipped`, `end_clipped`). Dasselbe gilt für die
  Arten, deren Zählungen dann diese Schritte nicht enthalten. Kurz gesagt:
  starte Home Assistant nicht während eines heftigen Wolkenbruchs neu.
- Die Aufzeichnung übersteht Neustarts und Optionsänderungen. Wenn du den
  Konfigurationseintrag der Integration löschst, wird sie mitgelöscht.
- [ADR 0006](/development/adr/0006-rain-events-opt-in-entity) erklärt, warum
  die Ereignisse eine eigene, optional zuschaltbare Entität sind und bei jeder
  Veröffentlichung neu berechnet werden,
  [ADR 0012](/development/adr/0012-rain-event-types-are-measured-only), warum
  sie erst eine Art haben, wenn sie gemessen ist.
