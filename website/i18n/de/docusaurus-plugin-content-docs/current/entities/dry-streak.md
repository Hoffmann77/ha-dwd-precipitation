---
title: Zeitraum ohne Niederschlag
description: Der Zähler für Tage ohne Regen, was ihn zurücksetzt und wie er mit Neustarts und Ausfällen umgeht.
---

**Zeitraum ohne Niederschlag** (Tage) zählt die Zeit, seit es an deinem
Standort zuletzt genug geregnet hat. Er eignet sich für
Bewässerungsautomationen: „Garten nach drei trockenen Tagen gießen“.

| Attribut | Bedeutung |
|----------|-----------|
| `hours_without_precipitation` | Dieselbe Trockenphase in Stunden; `null`, bis der Zähler begonnen hat |
| `dry_since` | Der Zeitpunkt, ab dem der Zähler zählt, ISO-8601 UTC: das Ende der Stunde, die ihn zuletzt zurückgesetzt hat, oder bei einer neuen Installation der Beginn der Trockenphase, die die Daten des DWD zeigen |

Eine neue Installation beginnt nicht bei null: der Zähler beginnt so weit
zurück, wie die angeeichten Analysen des DWD belegen, dass es trocken war, bis
zu 24 Stunden (wenn `Niederschlag letzte 24h` unter dem Schwellwert blieb). Er
zählt über Neustarts hinweg weiter.

## Was ihn zurücksetzt {#what-resets-it}

Zwei Optionen entscheiden das:

- [**Regenmenge, die den Trockenzähler zurücksetzt**](../getting-started/configuration.md#dry-streak-threshold)
  (Standard 1,0 mm): erreicht oder übersteigt die Summe der vergangenen Stunde
  diesen Wert, wird der Zähler zurückgesetzt. Es ist eine Menge innerhalb der
  Stunde, keine Rate.
- [**Produkt, das den Trockenzähler zurücksetzt**](../getting-started/configuration.md#dry-streak-source)
  wählt, welche Summe der vergangenen Stunde verglichen wird:

| Quelle | Aktualisiert | Ein Zurücksetzen zeigt sich | Hinweise |
|--------|--------------|-----------------------------|----------|
| **Angeeichte Stunde (RW)** | alle 10 min | 30 bis 40 min nach dem Regen | Mit Niederschlagsmessern korrigiert, genauer. Standard für neue Installationen |
| **Niederschlag letzte 60 min (RS)** | alle 5 min | wenige Minuten nach dem Regen | Nur Radar, stärker schwankend; seine gleitende Stunde setzt den Zähler noch bis zu eine Stunde nach Regenende immer wieder zurück |

Mit RW folgt der Zähler den Neuberechnungen der Analyse, die der DWD alle
10 Minuten macht, jede für die Stunde, die dann endet. Ein Zurücksetzen
verschiebt `dry_since` auf das Ende dieser Stunde.

Installationen, die eingerichtet wurden, bevor es die Option für die Quelle
gab, behalten RS, ein Update ändert also nichts. Wenn du wechselst, behält der
Zähler seinen Wert.

Es gibt bewusst keinen Rückgriff auf das andere Produkt: solange das gewählte
nicht verfügbar ist, ist es auch der Zähler nicht.

## Neustarts und Ausfallzeiten {#restarts-and-downtime}

Solange Home Assistant nicht läuft, wird nichts gemessen. Beim Start holt der
Zähler aus den RADOLAN-Analysen auf:

- hat die letzte RW-Stunde den Schwellwert erreicht, beginnt der Zähler am
  Ende dieser Stunde neu;
- sonst, wenn die vergangenen 24 Stunden von SF ihn erreicht haben, beginnt er
  am Anfang dieser 24 Stunden neu, da SF nicht sagen kann, wann innerhalb des
  Tages es geregnet hat.

Die Stunden der Zeit, in der Home Assistant nicht lief, werden danach außerdem
einzeln geprüft, wie im nächsten Abschnitt beschrieben; damit wird Regen in
dieser Zeit der richtigen Stunde zugeordnet.

## Ausfälle: Stunden ohne Daten werden später geprüft {#outages-hours-without-data-are-checked-later}

Ein Wert ohne Daten (`unknown` („Unbekannt“), zum Beispiel solange ein Radar
im Komposit des DWD fehlt) kann den Zähler nicht zurücksetzen, sodass Regen in
einer solchen Lücke übersehen würde. Hatte die Quelle länger als eine Stunde
keine Daten für deinen Standort, werden die verpassten vollen Stunden gegen
die angeeichte Stunde des DWD (`Niederschlag vorige Stunde`) geprüft, sobald
die Quelle wieder Werte liefert: eine Stunde, die den Schwellwert erreicht
hat, setzt den Zähler auf das Ende dieser Stunde zurück. Dieselbe Prüfung
deckt die Zeit ab, in der Home Assistant nicht lief, und die Zeit, in der der
DWD nicht veröffentlicht hat.

Die Stunden werden im Hintergrund abgerufen, die neueste zuerst. Der DWD hält
sie zwei Tage vor, eine ältere Lücke wird also nicht geprüft. Die Begründung
steht in
[ADR 0011](/development/adr/0011-dry-streak-gaps-checked-against-rw).
