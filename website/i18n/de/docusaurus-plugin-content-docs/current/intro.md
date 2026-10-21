---
title: Einführung
slug: /
description: Radar-Niederschlagsmessungen und -vorhersagen des Deutschen Wetterdienstes (DWD) für deinen genauen Standort in Home Assistant.
---

**DWD Precipitation** ist eine benutzerdefinierte Integration für
[Home Assistant](https://www.home-assistant.io/), die das Niederschlagsradar
des Deutschen Wetterdienstes (DWD) auf deinen genauen Standort bringt: wie
viel Regen gefallen ist, wie viel in den nächsten zwei Stunden kommt, wie
stark es regnet und was gerade fällt.

:::warning[Nur Deutschland]

Die Integration **funktioniert nur für Standorte in Deutschland** und einem
schmalen Streifen jenseits der Grenzen. Die Radarkomposits des DWD decken
andere Länder nicht ab.

:::

## Funktionen {#features}

- **Standortgenau:** Jeder Wert stammt aus der etwa 1 km × 1 km großen
  Gitterzelle des Radars, in der deine Koordinaten liegen.
- **Live:** Die Nowcast-Sensoren (Kurzfristvorhersage) werden alle 5 Minuten
  aktualisiert.
- **Vorhersage für zwei Stunden:** Vorhersagesummen, Spitzenintensität, die
  nasseste kommende Stunde und wann der Regen beginnt und aufhört.
- **Niederschlagsart:** Regen, Nieselregen, Schnee, Schneeregen, Graupel,
  Hagel, gefrierender Regen.
- **Gemessene Summen:** die vergangene Stunde, die vergangenen 24 Stunden,
  gestern und ein Zähler für die Tage ohne Regen.
- **Langfristige Summen:** laufende Regensummen für die Statistiken von Home
  Assistant, sodass Tages-, Wochen-, Monats- und Jahressummen sofort
  funktionieren.
- **Regenereignisse für Blueprints** (optional): Jeder Regenschauer wird unter
  einer ID von der Vorhersage bis zur Messung verfolgt, mit vorhergesagter und
  gemessener Menge nebeneinander.
- **Kein Konto, kein API-Schlüssel:** Die Daten stammen von
  [DWD Open Data](https://opendata.dwd.de/), das jeder herunterladen kann.

## Die gelesenen DWD-Produkte {#the-dwd-products-it-reads}

Die Integration liest fünf Produkte des DWD. Jedes hat seinen eigenen
Aktualisierungsrhythmus, und die Entitäten sind in dieser Dokumentation nach
Produkt gruppiert.

| Produkt | Was es ist | Aktualisiert | Entitäten |
|---------|------------|--------------|-----------|
| **RADVOR RS** | Radar-Nowcast: gleitende 60-Minuten-Summen, gemessen und vorhergesagt | alle 5 min | [Niederschlag letzte / nächste 60 min, …](entities/radvor-rs.md) |
| **RADVOR RV** | Radar-Nowcast in 5-Minuten-Schritten, zwei Stunden voraus | alle 5 min | [Intensität, Spitzen, Beginn und Ende, …](entities/radvor-rv.md) |
| **HymecNG** | Aus dem Radar klassifizierte Niederschlagsart | alle 5 min | [Niederschlagsart aktuell](entities/hymecng.md) |
| **RADOLAN RW** | Radaranalyse einer Stunde, mit Niederschlagsmessern angeeicht | stündlich | [Niederschlag vorige Stunde, Niederschlag gesamt](entities/radolan.md) |
| **RADOLAN SF** | Radaranalyse von 24 Stunden, mit Niederschlagsmessern angeeicht | stündlich / täglich | [Niederschlag letzte 24h, gestern](entities/radolan.md) |

Die Werte von RADVOR und HymecNG stammen nur vom Radar und sind schnell. Die
Werte von RADOLAN sind mit Messungen von Niederschlagsmessern angeeicht: Sie
kommen etwa 30 Minuten später, sind aber genauer.
[Die DWD-Produkte](how-it-works/dwd-products.md) erklärt den Unterschied.

## Wie es weitergeht {#where-to-go-next}

- [Installiere die Integration](getting-started/installation.md), dann
  [richte sie ein und wähle deine Optionen](getting-started/configuration.md).
- [Entitäten](entities/overview.md) listet jeden Sensor mit Einheit und
  Aktualisierungsintervall auf.
- Sieht etwas falsch aus? Sieh unter [Fehlerbehebung](help/troubleshooting.md)
  und in den [häufigen Fragen](help/faq.md) nach.
- Du aktualisierst von einer Version vor 2026.11.0?
  [Aktualisieren](help/upgrading.md) listet, was sich geändert hat,
  einschließlich der umbenannten Entitäten.

:::info

Dies ist ein Community-Projekt. Es steht in keiner Verbindung zum Deutschen
Wetterdienst und wird nicht von ihm unterstützt. Alle Daten sind © DWD und
werden gemäß den
[Nutzungsbedingungen von DWD Open Data](https://www.dwd.de/EN/service/legal_notice/legal_notice_node.html)
verwendet.

:::
