---
title: Regenwarnungen
description: Deine eigenen Warnungen, etwa „Wäsche, 60 Minuten vorher“, jede mit einer An/Aus- und einer Status-Entität.
---

Eine **Regenwarnung** geht an, kurz bevor Regen deinen Standort erreicht, und
bleibt an, solange es regnet. Du legst fest, wie früh, und auf Wunsch, wie
viel Regen eine Warnung wert ist: „Wäsche, 60 Minuten vorher“, „Fenster,
15 Minuten vorher, nur bei einem heftigen Schauer“. Du kannst beliebig viele
anlegen.

Regenwarnungen brauchen weder Blueprint noch Template: Jede ist ein Gerät mit
zwei Entitäten, auf die eine Automation auslösen kann.

## Eine Warnung hinzufügen {#adding-a-warning}

Öffne **Einstellungen > Geräte & Dienste > DWD Precipitation** und wähle am
Eintrag des Standorts **Regenwarnung hinzufügen**. Das Formular fragt nach:

| Feld | Standard | Bedeutung |
|------|----------|-----------|
| Name | | Wofür die Warnung ist, etwa `Wäsche`. Jede Warnung eines Standorts braucht einen eigenen Namen |
| Vorlaufzeit | 30 min | Wie viele Minuten vor dem Regen die Warnung angeht, von 5 bis 120 in 5er-Schritten |
| Mindestregen insgesamt | leer | Nur vor einem Regenereignis warnen, das mindestens so viel bringt, gemessen und vorhergesagt (mm) |
| Mindestregen in der nassesten Stunde | leer | Nur vor einem Ereignis warnen, dessen nasseste Stunde mindestens so viel bringt (mm) |
| Mindestregen in den nassesten 10 Minuten | leer | Nur vor einem Ereignis warnen, dessen nasseste 10 Minuten mindestens so viel bringen (mm), für kurze, heftige Schauer |
| Bei mehreren Mindestwerten | einer genügt | Ob ein Ereignis einen der gesetzten Mindestwerte erreichen muss oder alle |

Lass alle Mindestwerte leer, um vor jedem Regenereignis gewarnt zu werden.

Um eine Warnung später zu ändern, öffne ihr Menü am Eintrag und wähle
**Neu konfigurieren**. Löschst du sie, verschwinden ihr Gerät und ihre
Entitäten. Hinzufügen, Ändern und Löschen einer Warnung lädt die Integration
neu; die Werte sind nach ein paar Sekunden wieder da. Die Vorwarnzeit allein
lässt sich auch am Regler **Vorwarnzeit** der Warnung ändern (siehe unten);
das wirkt sofort und lädt nichts neu.

## Entitäten {#entities}

Jede Warnung ist ein eigenes Gerät, benannt nach dem Standort und der Warnung:
Eine Warnung `Wäsche` am Standort `Home` ist das Gerät `Home Wäsche` mit:

| Entität | Entitäts-ID | Zustände |
|---------|-------------|----------|
| Regenwarnung | `binary_sensor.home_wasche_rain_warning` | `on`, solange es regnet oder gleich regnet, sonst `off` |
| Regenwarnung Status | `sensor.home_wasche_rain_warning_status` | `dry`, `soon` oder `rain` |
| Vorwarnzeit | `number.home_wasche_lead_time` | die Vorwarnzeit in Minuten, 5 bis 120; Verstellen ändert die Warnung sofort und speichert den Wert in ihren Einstellungen |

Der Status-Sensor trägt die Details als Attribute; die An/Aus-Entität hat
keine.

| Status | Bedeutung |
|--------|-----------|
| `rain` (Regen) | ein Regenereignis, das die Mindestwerte der Warnung erreicht, fällt gerade |
| `soon` (Bald) | keines fällt, aber eines, das sie erreicht, beginnt innerhalb der Vorlaufzeit |
| `dry` (Trocken) | weder noch |

Benennst du eine Warnung um, bekommen ihr Gerät und ihre Entitäten den neuen
Namen; die Entitäts-IDs bleiben, wie sie waren, sodass deine Automationen
weiter funktionieren.

Beide Entitäten sind `unknown`, solange es noch nichts zu beurteilen gibt,
etwa ein paar Sekunden nach einem Neustart, und `unavailable`, wenn die
Radarvorhersage veraltet ist, wie die anderen Vorhersagesensoren.

## Attribute {#attributes}

| Attribut | Beschreibung |
|----------|--------------|
| `event_id` | Die ID des Regenereignisses, um das es geht, wie in [Regenereignisse](rain-events.md#events) |
| `start` | Wann dieses Ereignis beginnt (oder begonnen hat), ISO-8601 in UTC |
| `end` | Wann es voraussichtlich endet, ISO-8601 in UTC; bei `beyond_horizon` nur das Ende der Vorhersage |
| `beyond_horizon` | `true`, solange das Ereignis über den Vorhersagehorizont (etwa zwei Stunden) hinausgeht, sein Ende also offen ist |
| `mm` | Seine Summe: bisher gemessen plus vorhergesagt, in mm |
| `peak_1h` | Der Regen in seiner nassesten Stunde, in mm |
| `peak_10min` | Der Regen in seinen nassesten 10 Minuten, in mm |
| `type` | Die gemessene Niederschlagsart des Ereignisses, etwa `rain` oder `snow`, wie in [Regenereignisse](rain-events.md); `null`, solange es nur vorhergesagt ist, da der DWD keine Art vorhersagt |
| `expected_type` | Der gemessene `type`, sobald es ihn gibt; davor eine Schätzung: die Art des nächstgelegenen Niederschlags, den das Radar im Umkreis von 5 km sieht, etwa `snow`, wenn Schnee heranzieht. `null`, wenn dort keiner ist |

Alle sind `null`, solange der Status `dry` ist, und keines wird im Verlauf
aufgezeichnet.

## Wie eine Warnung entscheidet {#how-a-warning-decides}

Eine Warnung hat keine eigene Regenlogik: Sie liest die Regenereignisse, die
die Integration für den Standort verfolgt, dieselben, die der Sensor
[Regenereignisse](rain-events.md) zeigt. Was als Regen zählt, legt daher die
Option
[*Nur Regen zählen, der stärker ist als*](../getting-started/configuration.md#rain-event-threshold)
im Abschnitt *Regenereignisse und Regenwarnungen* fest, und die Vorhersage reicht zwei Stunden voraus.

- Die Vorlaufzeit zählt ab dem Moment, in dem die Radardaten in Home
  Assistant ankommen. Sie kommen alle 5 Minuten, daher kann eine Warnung bis
  zu 5 Minuten später angehen, als die Vorlaufzeit sagt. Die DWD-Daten sind
  bei ihrer Ankunft schon ein paar Minuten alt (siehe
  [Veröffentlichungszeitpunkte](../how-it-works/release-timing.md)), eine kurze
  Vorlaufzeit lässt also weniger Zeit, als sie verspricht: Nimm mindestens 10
  oder 15 Minuten für alles, was etwas dauert.
- Die Mindestwerte werden mit der Summe des Ereignisses verglichen: was
  bisher gefallen ist plus was vorhergesagt ist. Ein bevorstehendes Ereignis
  hat nur seine Vorhersage.
- Hat ein Ereignis die Mindestwerte einmal erreicht, zählt es, bis es vorbei
  ist, auch wenn eine spätere Vorhersage es kleiner macht. Ein Schauer
  schaltet die Warnung nicht aus und wieder an, nur weil sich seine
  Vorhersage geändert hat.
- Eine Vorhersage verliert einen kleinen Schauer oft für eine
  Veröffentlichung und findet ihn in der nächsten wieder. Eine Warnung, die
  `soon` war, bleibt für diese eine Veröffentlichung `soon`; fehlt der Schauer
  auch in der nächsten, geht die Warnung zurück auf `dry`.
- Beides merkt sich die Integration nur im Arbeitsspeicher. Nach einem
  Neustart wird ein Ereignis neu nach seinen aktuellen Werten beurteilt.

## Gut zu wissen {#good-to-know}

- Regenwarnungen nutzen die Verfolgung der Regenereignisse, aber nicht den
  Sensor `Regenereignisse`: Sie funktionieren auch mit ausgeschalteter Option
  *Sensor „Regenereignisse“ hinzufügen*. Solange ein Standort eine Warnung hat, ruft
  die Integration verpasste Radaranalysen ab (einen kleinen Teil jeder Datei)
  und speichert eine kleine Aufzeichnung des jüngsten Regens. Löschst du die
  letzte Warnung bei ausgeschalteter Option, wird
  diese Aufzeichnung gelöscht.
- Die Mengen kommen nur vom Radar, wie die
  [Regenereignisse](rain-events.md#good-to-know), aus denen sie stammen.
- Regenwarnungen brauchen Home Assistant 2025.4 oder neuer.
