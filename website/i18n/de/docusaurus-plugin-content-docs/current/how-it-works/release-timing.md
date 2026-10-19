---
title: Veröffentlichungszeitpunkte
description: Wann jedes DWD-Produkt veröffentlicht und abgerufen wird, warum Werte erst Minuten nach ihrem Termin ankommen und wie fehlgeschlagene Abrufe wiederholt werden.
---

Die Integration fragt nicht in einem festen Intervall ab. Jedes Produkt wird
abgerufen, wenn der DWD seine nächste Datei voraussichtlich veröffentlicht
hat, und erneut versucht, wenn nicht.

## Wann jedes Produkt abgerufen wird {#when-each-product-is-fetched}

Jede DWD-Datei hat einen Termin: das Ende des Zeitfensters, das sie misst,
oder den Analysezeitpunkt, von dem eine Vorhersage ausgeht. Auf Open Data
erscheint sie einige Minuten später. Die Integration ruft jedes Produkt zu
seinem Termin plus dieser Verzögerung ab:

| Produkt | Termine | Veröffentlicht etwa | Abgerufen um |
|---------|---------|---------------------|--------------|
| RADVOR RS, RV | alle 5 min (:00, :05, …) | 4 min später | :04, :09, … |
| HymecNG | alle 5 min | 3 min später | :03, :08, … |
| RADOLAN RW | stündlich, zur vollen Stunde | 28 min später | :28 |
| RADOLAN RW, 10-Minuten-Läufe¹ | alle 10 min | 28 min später | :08, :18, … |
| RADOLAN SF | stündlich um :50 | 31 min später | :21 |
| RADOLAN SF, gestern | täglich um 23:50 deutscher Ortszeit | 31 min später | 00:21 Ortszeit |

¹ Wird nur abgerufen, wenn
[Zeitraum ohne Niederschlag](../entities/dry-streak.md) RW zählt.

Zusätzlich bekommt jede Installation einen eigenen festen Versatz von bis zu
30 Sekunden, damit nicht jedes Home Assistant in Deutschland in derselben
Sekunde beim DWD anfragt. Der Versatz wird aus dem Konfigurationseintrag
abgeleitet und bleibt deshalb über Neustarts hinweg gleich.

Die Verzögerungen werden von einem zeitgesteuerten Job in der CI des Projekts
mit dem abgeglichen, was der DWD tatsächlich tut. Er eröffnet ein Issue, wenn
der DWD später veröffentlicht, als die Integration erwartet.

## Warum „aktuell“ ein paar Minuten alt ist {#why-now-is-a-few-minutes-old}

Ein Wert beschreibt sein DWD-Zeitfenster, nicht den Moment, in dem er in Home
Assistant erscheint. `Niederschlagsintensität aktuell` aus der
Veröffentlichung zum Termin 14:00 beschreibt 13:55–14:00 und erscheint gegen
14:04. Wenn du ihn siehst, ist er also etwa 4 bis 10 Minuten alt, je nachdem,
wann innerhalb der 5 Minuten du hinschaust. Dasselbe gilt für
`Niederschlagsart aktuell` und `Niederschlag letzte 60 min`.

Auch die Vorhersagen zählen ab dem Termin der Veröffentlichung: Um 14:04
deckt `Niederschlag nächste 60 min` noch 14:00–15:00 ab.

## Wenn der DWD spät dran ist {#when-dwd-is-late}

Der DWD veröffentlicht oft ein paar Minuten zu spät, deshalb ist eine Datei,
die beim ersten Versuch noch nicht da ist, normal und kein Fehler. Die
Integration versucht es dann erneut:

- der erste erneute Versuch nach 60 Sekunden,
- jeder weitere 10 Sekunden später als der vorige,
- bis hin zu alle 5 Minuten (15 Minuten für `Niederschlag gestern`), und in
  diesem Takt so lange, wie der Ausfall dauert.

Jeder erneute Versuch wird um bis zu 15 % variiert, damit Installationen, die
gemeinsam gescheitert sind, es nicht gemeinsam erneut versuchen. Nur ein
erfolgreicher Abruf setzt den Takt zurück, sodass sich ein langer Ausfall des
DWD beim langsamsten Takt einpendelt, statt jede Minute nachzufragen.

Das Protokoll bekommt eine Meldung pro Fehlerserie, die sagt, was der DWD
getan hat, zum Beispiel dass eine Veröffentlichung noch nicht erschienen
ist. Ob die Sensoren in der Zwischenzeit verfügbar bleiben, erklärt
[Verfügbarkeit und Aktualität](availability.md).
