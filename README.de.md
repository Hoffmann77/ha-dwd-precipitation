# DWD Precipitation

[English](https://github.com/Hoffmann77/ha-dwd-precipitation/blob/main/README.md) | **Deutsch**

[![Dokumentation](https://img.shields.io/badge/Doku-online%20lesen-blue.svg)](https://hoffmann77.github.io/ha-dwd-precipitation/de/)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/Hoffmann77/ha-dwd-precipitation)](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
[![Tests](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml)
[![HACS Validate](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml)

Radarbasierte Niederschlagsmessungen und -vorhersagen des Deutschen Wetterdienstes (DWD), für deinen genauen Standort, direkt in Home Assistant.

> [!IMPORTANT]
> Diese Integration funktioniert **nur** für Standorte **in Deutschland** und in Gebieten direkt an der deutschen Grenze.
> Die Radarkomposits des DWD decken andere Länder nicht ab.

> [!TIP]
> **[Zur Dokumentation](https://hoffmann77.github.io/ha-dwd-precipitation/de/)**: jeder Sensor, jede Option, wie alles funktioniert, und Hilfe bei Problemen. Auch [auf Englisch](https://hoffmann77.github.io/ha-dwd-precipitation/).
>
> [Installation](https://hoffmann77.github.io/ha-dwd-precipitation/de/getting-started/installation) · [Konfiguration](https://hoffmann77.github.io/ha-dwd-precipitation/de/getting-started/configuration) · [Entitäten](https://hoffmann77.github.io/ha-dwd-precipitation/de/entities/overview) · [Regenwarnungen](https://hoffmann77.github.io/ha-dwd-precipitation/de/entities/rain-warnings) · [Häufige Fragen](https://hoffmann77.github.io/ha-dwd-precipitation/de/help/faq) · [Fehlerbehebung](https://hoffmann77.github.io/ha-dwd-precipitation/de/help/troubleshooting)

## Funktionen

- **Standortgenau:** Die Werte stammen aus der etwa 1 km großen Gitterzelle des Radars, die deine Koordinaten enthält
- **Aktuell:** Die Sensoren der Kurzfristvorhersage werden alle 5 Minuten aktualisiert
- **Zwei-Stunden-Vorhersage:** vorhergesagte Mengen, Spitzenintensität, die nasseste Stunde und wann der Regen beginnt und aufhört
- **Niederschlagsart:** Regen, Nieselregen, Schnee, Schneeregen, Graupel, Hagel, gefrierender Regen
- **Gemessene Summen:** vorige Stunde, letzte 24 Stunden, gestern, und ein Zähler für die Tage ohne Regen
- **Langzeitsummen:** laufende Regensummen für die Statistik von Home Assistant, sodass Wochen-, Monats- und Jahressummen sofort funktionieren
- **Regenwarnungen:** deine eigenen Warnungen, etwa „Wäsche, 60 Minuten vorher“, jede eine An/Aus-Entität für Automationen, auf Wunsch nur für Regen ab einer Mindestmenge
- **Regenereignisse für Blueprints** (optional): jeder Schauer, verfolgt von der ersten Vorhersage, bis er vorbei ist, mit vorhergesagten und gemessenen Mengen nebeneinander
- **Einstellbare Schwellen:** Lege fest, wie viel Regen zählt, für die Vorhersagesensoren wie für die Regenereignisse

## Entitäten

Alle Entitäten gehören zu einem Gerät **DWD Precipitation** pro eingerichtetem Standort (Regenwarnungen sind jeweils ein eigenes Gerät):

- **Radar-Kurzfristvorhersage, alle 5 Minuten:** Niederschlag letzte 60 min, nächste 60 min, nächste 60–120 min und nächste 120 min; Niederschlagsintensität aktuell; Spitzenintensität nächste 60 min, nächste 60–120 min und nächste 120 min; Maximaler Stundenniederschlag nächste 120 min; Niederschlagsbeginn und -ende; Niederschlag erwartet; Niederschlagsart aktuell
- **Angeeichte Analysen, stündlich und täglich:** Niederschlag vorige Stunde, letzte 24h und gestern
- **Für die Statistik:** Niederschlag gesamt und Niederschlag gesamt täglich
- **Zeitraum ohne Niederschlag**, und der optionale Sensor **Regenereignisse** für Blueprints
- **Regenwarnungen**, die du selbst hinzufügst, jede ein eigenes Gerät mit einer An/Aus- und einer Status-Entität

Die [Entitätsübersicht](https://hoffmann77.github.io/ha-dwd-precipitation/de/entities/overview) listet jede Entität mit ihrer ID, Einheit und Aktualisierungsrate.

> [!NOTE]
> Du aktualisierst von einer Version vor 2026.11.0? Mehrere Entitäten wurden umbenannt, und bestehende Installationen behalten ihre alten Entitäts-IDs. Siehe [Aktualisieren](https://hoffmann77.github.io/ha-dwd-precipitation/de/help/upgrading).

## Screenshots

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_config_flow.png" alt="Einrichtungsdialog mit dem Namensfeld und der Standortkarte." height="400"/>

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_entities_2026-8-0.png" alt="Geräteseite mit den Niederschlagssensoren und ihren aktuellen Werten." height="400"/>

## Installation

Falls du HACS noch nicht installiert hast, findest du die Anleitung unter https://hacs.xyz.

Um dieses Repository in HACS deiner Home-Assistant-Instanz hinzuzufügen, nutze diesen Button:

[![Öffne deine Home-Assistant-Instanz und ein Repository im Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=Integration)

Starte Home Assistant nach der Installation neu. Um DWD Precipitation zu deiner Home-Assistant-Instanz hinzuzufügen, nutze diesen Button:

[![Öffne deine Home-Assistant-Instanz und richte eine neue Integration ein.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dwd_precipitation)

Gib einen Namen ein und wähle den Standort; die [Konfigurationsanleitung](https://hoffmann77.github.io/ha-dwd-precipitation/de/getting-started/configuration) erklärt jede Option. Die manuelle Installation beschreibt die [Installationsanleitung](https://hoffmann77.github.io/ha-dwd-precipitation/de/getting-started/installation).

## Datenquelle

Alle Daten stammen vom **DWD (Deutscher Wetterdienst)**:

<img src="docs/assets/dwd-logo.png" alt="Logo des Deutschen Wetterdienstes" width="200"/>

**[Aktueller Status der Radarstationen des DWD](https://www.dwd.de/DE/leistungen/radarniederschlag/rn_info/home_freie_radarstatus_kartendaten.html)**

## Lizenz

Diese Integration steht unter der [Apache License 2.0](LICENSE).

Sie verdankt den Mitwirkenden des Pakets **[wradlib](https://github.com/wradlib/wradlib)** viel: Frühe Versionen enthielten Teile davon, und die Testsuite prüft jeden Parser und jede Gitterzellen-Suche weiterhin dagegen.
