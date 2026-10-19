---
title: Architektur
description: Die Module von DWD Precipitation, wie Daten von DWD Open Data zu einer Entität fließen und wie Fehler behandelt werden.
---

Die Integration ruft Radarkomposite des DWD ab, findet die Gitterzelle, die
den konfigurierten Standort enthält, und stellt deren Werte als Sensoren
bereit. Diese Seite ist der Überblick; `CLAUDE.md` im Repository legt die
genauen Regeln fest, und die [ADRs](/development/adr) die Begründungen
dahinter.

## Module {#modules}

| Modul | Aufgabe |
|-------|---------|
| `__init__.py` | Einstiegspunkt. Baut einen Coordinator pro Produkt, aktualisiert sie parallel und lässt jeden seinen Veröffentlichungsplan registrieren |
| `coordinator.py` | `BaseProductUpdateCoordinator`, der `DataUpdateCoordinator` pro Produkt: Veröffentlichungszeitpunkte, der Ablauf aus Abruf, Veralten und erneutem Versuch, die schrittweise längeren Abstände |
| `products.py` | Eine Coordinator-Unterklasse pro DWD-Produkt: URL, Abruf, Parsen, Gitterzellen-Suche |
| `entity.py` | `DwdCoordinatorEntity`, die Basis jeder Entität: Unique ID, Gerät, Verfügbarkeit, der Beschreibungsmechanismus |
| `sensor.py`, `binary_sensor.py` | Die Entitätsbeschreibungen und die besonderen Sensoren (Summen, Trockenzähler, Regenereignisse) |
| `dry_streak.py`, `precipitation_total.py` | Reine Logik des Trockenzählers und der laufenden Summen |
| `rain_events_tracker.py` | Die Regenereignisse eines Konfigurationseintrags in Home Assistant: Speicher, Nachfüllen im Hintergrund, Speicherstrategie |
| `release_grid.py` | `ReleaseGrid`: die Veröffentlichungstermine eines Produkts auf seiner eigenen Uhr |
| `config_flow.py`, `options.py` | Einrichtungs- und Optionsformular; `DwdOptions`, die Optionen als ein typisierter Schnappschuss |
| `utils.py` | Der HTTP-Helfer, ein Download-Cache pro Konfigurationseintrag, ein Fehler-Latch |
| `radar/` | Der Kern ohne Home Assistant: ODIM_H5-Leser, das Gitter, Range-Anfragen auf Tar-Archive, Nowcast- und Regenereignis-Logik |

`radar/` und `release_grid.py` importieren nichts aus Home Assistant, sodass
die Teststufen parser und reference sie ohne Home Assistant testen können.

## Datenfluss {#data-flow}

Es gibt keine gemeinsame Abfrageschleife: Jedes Produkt ist sein eigener
Coordinator, mit seinem eigenen Zeitplan.

1. Ein Time-Change-Tracker löst zum Veröffentlichungszeitpunkt des Produkts
   aus (sein Termin plus `RELEASE_DELAY` plus ein Versatz pro Installation)
   und fordert den Coordinator zur Aktualisierung auf.
2. Der Coordinator berechnet die neueste Veröffentlichung, die auf Open Data
   sein sollte. Hat er diese schon, gibt er die zwischengespeicherten Daten
   unverändert zurück.
3. `_fetch_and_parse(release)` lädt die Datei in der Event-Loop herunter und
   dekodiert sie dann im Executor: Ein Gitter mit 1,3 Millionen Zellen zu
   dekodieren braucht Zeit, und viele Nutzer betreiben Home Assistant auf
   einem Raspberry Pi. Der Parser liest die Zelle, die den Standort enthält,
   auf dem Gitter, das die Datei selbst beschreibt.
4. Das Ergebnis wird in ein `CoordinatorData` verpackt: die Dicts `data` und
   `metadata`, mit denselben Unterschlüsseln (`KEY_*` in `const.py`).
5. Jede Entität liest `data[sub_key]` und `metadata[sub_key]` des
   Coordinators ihres Produkts.

`_fetch_and_parse` hat keine Seiteneffekte, sodass sich jede vergangene
Veröffentlichung abrufen lässt, ohne den Coordinator zu bewegen; das
Nachholen der Summen und die Lückenprüfung des Trockenzählers verlassen sich
darauf. Was die Übernahme einer Veröffentlichung sonst noch tun soll, gehört
in `_async_on_new_release`, das nie eine Ausnahme wirft.

## Veröffentlichungszeitpunkte {#release-timing}

Jede Berechnung von Veröffentlichungen läuft über das `ReleaseGrid` des
Coordinators, auf der eigenen Uhr des Produkts: UTC für die meisten Produkte,
die lokale Zeitzone von Home Assistant für das tägliche `sf_2350`, dessen
Veröffentlichungen an den Tagen der Zeitumstellung 23 oder 25 Stunden
auseinanderliegen.

- `RELEASE_INTERVAL` und `RELEASE_OFFSET` beschreiben das Raster der Termine.
- `RELEASE_DELAY` gibt an, wie lange nach ihrem Termin eine Datei auf Open
  Data ist. Ein zeitgesteuerter Workflow gleicht ihn mit dem ab, was der DWD
  tatsächlich tut.
- Jede Installation addiert einen festen Versatz von bis zu 30 Sekunden, der
  aus der ID des Konfigurationseintrags abgeleitet (nicht zufällig gezogen)
  wird. So rufen nicht alle Installationen in derselben Sekunde ab, und eine
  Installation behält ihren Zeitplan über Neustarts hinweg.

[ADR 0007](/development/adr/0007-staleness-deadline-on-the-overdue-release)
erklärt, warum der Zeitplan auf der eigenen Uhr des Produkts registriert
wird.

## Fehlerbehandlung {#failure-handling}

Abrufe scheitern routinemäßig: Dass der DWD ein paar Minuten zu spät
veröffentlicht, ist der Normalfall.

- **Erneuter Versuch mit schrittweise längeren Abständen.** Der erste Fehler
  plant einen erneuten Versuch nach 60 Sekunden, jeder weitere addiert
  10 Sekunden, begrenzt auf 5 Minuten (15 für `sf_2350`). Nur ein Erfolg
  setzt das zurück. Jeder erneute Versuch bekommt ±15 % Streuung, damit
  Installationen, die gemeinsam gescheitert sind, es nicht im Gleichschritt
  erneut versuchen.
- **Veralten ist eine Frist auf die überfällige Veröffentlichung.** Ein Wert
  wird nicht mehr gemeldet, sobald `OVERDUE_GRACE` (6 Minuten; 30 für
  `sf_2350`) verstrichen ist, seit die Veröffentlichung fällig war, die ihn
  hätte ersetzen sollen. `data_is_reportable` ist die einzige Stelle, an der
  diese Entscheidung fällt. Siehe
  [ADR 0007](/development/adr/0007-staleness-deadline-on-the-overdue-release).
- **Ein ausgefallenes Produkt legt den Konfigurationseintrag nicht lahm.**
  Die Einrichtung scheitert nur, wenn jedes Produkt scheitert.
- **Eine Zelle ohne Daten wird beim Wechsel protokolliert.** Fällt ein Radar
  aus dem Komposit des DWD heraus, gelingt jeder Abruf weiterhin, aber die
  Zelle ist leer; der Coordinator protokolliert eine Warnung, wenn die Daten
  wegfallen (mit den fehlenden Radaren), und eine Meldung, wenn sie zurück
  sind.

`_describe_fetch_error()` schreibt die Meldung, die ein Nutzer sieht, einmal
pro Fehlerserie. Sie nennt, was der DWD getan hat, sagt, ob die Konfiguration
beteiligt ist, und hält fest, dass die erneuten Versuche weiterlaufen, in
reinem ASCII.

## Gitterzellen-Suche {#grid-lookup}

Jedes Produkt liest die Zelle, die den Standort enthält, auf dem Gitter, das
seine eigene Datei in ihrer ODIM-Gruppe `/where` beschreibt
([ADR 0010](/development/adr/0010-cells-on-the-grid-each-file-describes)).
`radar/grid.py` baut das Gitter; berechnet wird nur die nordpolare
stereografische Projektion auf einem Ellipsoid, und alles andere, was eine
Zelle verschieben könnte, wird abgelehnt, statt an der falschen Stelle
gelesen zu werden.

Die Suche projiziert den Standort und rundet seinen Abstand von der äußeren
unteren linken Ecke des Gitters ab: Die Eckangaben sind Pixelkanten, keine
Mittelpunkte
([ADR 0008](/development/adr/0008-grid-lookup-floors-from-the-outer-corner)).

## Range-Anfragen {#range-reads}

Die Archive von RS und RV sind einfache Tar-Dateien mit 25 Einträgen. RS
braucht nur drei davon, deshalb liest `radar/tar_range.py` diese per
Range-Anfrage (HTTP-Teildownload): Eine Range-Anfrage auf die ersten 128 KiB
liefert den ersten Eintrag und die Dateigröße, und die übrigen werden durch
Interpolation zwischen bekannten Headern gefunden. Bei allem Unerwarteten
wird auf das ganze Archiv zurückgegriffen, mit einer Warnung pro Serie
solcher Rückfälle.

## Die besonderen Sensoren {#the-special-sensors}

- **Laufende Summen** hängen an der Veröffentlichung, nie an einer Änderung
  des Werts, und holen verpasste Veröffentlichungen aus einer gespeicherten
  Liste offener Einträge nach
  ([ADR 0005](/development/adr/0005-running-totals)).
- **Zeitraum ohne Niederschlag** bindet sich an den Coordinator der gewählten
  Quelle; RW wird aus seinen 10-Minuten-Läufen gezählt
  ([ADR 0003](/development/adr/0003-rw-10-minute-runs-only-for-the-dry-streak)),
  und Lücken werden gegen die Stunden von RW geprüft
  ([ADR 0011](/development/adr/0011-dry-streak-gaps-checked-against-rw)).
- **Regenereignisse** werden bei jeder Veröffentlichung aus den gespeicherten
  gemessenen Schritten neu berechnet, statt aufaddiert zu werden
  ([ADR 0006](/development/adr/0006-rain-events-opt-in-entity)).

## Benennung der Entitäten {#entity-naming}

Jeder Entitätsname kommt aus einem `translation_key` und
`translations/en.json`; Home Assistant leitet die Entitäts-ID aus dem
englischen Namen ab. Eine veröffentlichte ID wird nie für einen anderen Wert
wiederverwendet, und Entitätsschlüssel (das Suffix der Unique ID) ändern sich
nach der Veröffentlichung nie
([ADR 0001](/development/adr/0001-entity-names-state-their-window)).
