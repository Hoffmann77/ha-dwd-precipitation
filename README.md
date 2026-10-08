# DWD Precipitation

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/Hoffmann77/ha-dwd-precipitation)](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
[![Tests](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml)
[![HACS Validate](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml)

Radarbasierte Niederschlagsmessungen und -vorhersagen des Deutschen Wetterdienstes (DWD) für deinen genauen Standort, direkt in Home Assistant.

*English version: see [below](#english-version).*

> [!IMPORTANT]
> **⚠️ Wichtig:**
> Diese Integration funktioniert **nur** für Standorte **in Deutschland** und in Gebieten direkt an der deutschen Grenze.
> Die Radarkomposite des DWD decken andere Länder nicht ab.

## Funktionen

- **Standortgenau:** Die Werte stammen aus der etwa 1 km großen Radar-Gitterzelle, in der deine Koordinaten liegen
- **Live:** Die Nowcast-Sensoren werden alle 5 Minuten aktualisiert
- **Zwei-Stunden-Vorhersage:** vorhergesagte Mengen, Spitzenintensität sowie Beginn und Ende des Regens
- **Niederschlagsart:** Regen, Nieselregen, Schnee, Schneeregen, Graupel, Hagel, gefrierender Regen
- **Gemessene Mengen:** letzte Stunde, letzte 24 Stunden, gestern und ein Zähler für Tage ohne Regen
- **Langzeitsummen:** fortlaufende Regensummen für die Statistik von Home Assistant, damit Wochen-, Monats- und Jahressummen ohne weiteres funktionieren
- **Einstellbare Schwellen** für Regenereignisse, die sich in Automationen nutzen lassen.
- **Umkreis-Auswertung**: Regen knapp neben der eigenen Zelle wird nicht mehr verpasst; der nächste Niederschlag im 5-km-Umkreis wird mit Entfernung und Himmelsrichtung gemeldet
- **Regenwarnung**: fertiger Warnsensor `dry` / `soon` / `rain` mit einstellbarer Vorwarnzeit und Rauschfilter gegen Fehlalarme, dazu ein Blueprint für Benachrichtigungen

## Entitäten

Alle Entitäten gehören zu einem Gerät **DWD Precipitation** pro eingerichtetem Standort. In Klammern steht der Name in der deutschen Oberfläche.

Namen mit **`last <N>`** („letzte <N>“) sind gemessene Mengen über den Zeitraum, der jetzt endet.

Namen mit **`next <N>`** („nächste <N>“) sind Vorhersagen.

> [!Note]
> **ℹ️ Hinweis:**
> **`next 1–2h`** ist die *zweite* Stunde voraus (60–120 min), nicht die kommenden zwei Stunden.

**RADVOR RS: Radar-Nowcast · Aktualisierung alle 5 min**

- **Precipitation now** („Niederschlag aktuell“, mm): Regen, der in den letzten 60 Minuten gefallen ist. Das ist eine Menge, keine Rate in mm/h.
- **Precipitation next 1h** („Niederschlag nächste 1h“, mm): vorhergesagte Menge für die nächsten 0–60 min
- **Precipitation next 1–2h** („Niederschlag nächste 1–2h“, mm): vorhergesagte Menge für 60–120 min ab jetzt
- **Peak hourly precipitation next 2h** („Maximaler Stundenniederschlag nächste 2h“, mm): das nasseste 60-Minuten-Fenster, das für die nächsten 2 h vorhergesagt ist
- **Timespan without precipitation** („Zeitraum ohne Niederschlag“, Tage): Zeit, seit `Precipitation now` zuletzt die Rücksetzschwelle erreicht hat.

**RADVOR RV: Nowcast in 5-Minuten-Schritten · Aktualisierung alle 5 min**

- **Peak intensity next 1h** („Spitzenintensität nächste 1h“, mm/h): stärkste erwartete Regenrate in den nächsten 0–60 min
- **Peak intensity next 1–2h** („Spitzenintensität nächste 1–2h“, mm/h): dasselbe für 60–120 min
- **Precipitation start** („Niederschlagsbeginn“, Uhrzeit oder min): wann der Regen beginnt; `unknown`, wenn innerhalb von 2 h keiner kommt
- **Precipitation end** („Niederschlagsende“, Uhrzeit oder min): wann der Regen aufhört; `unknown`, wenn er länger als 2 h anhält
- **Precipitation expected** („Niederschlag erwartet“, Binärsensor): `on`, wenn innerhalb von 2 h Regen vorhergesagt ist
- **Precipitation start nearby** („Niederschlagsbeginn Umkreis“, Uhrzeit oder min): wann der Regen im Umkreis von etwa 1 km beginnt; `unknown`, wenn innerhalb von 2 h keiner kommt
- **Nearest precipitation** („Nächster Niederschlag“, km): Entfernung zum nächsten Niederschlag im 5-km-Umkreis, mit Himmelsrichtung als Attribut; `unknown`, wenn im Umkreis nichts fällt

**HymecNG: Niederschlagsart · Aktualisierung alle 5 min**

- **Precipitation type** („Niederschlagsart“): was gerade fällt: Regen, Nieselregen, Schnee, Schneeregen, Graupel, Hagel, gefrierender Regen, …

**RADOLAN RW / SF: Analyse aus Radar und Regenmessern · Aktualisierung stündlich / täglich**

- **Precipitation last 1h** („Niederschlag letzte 1h“, mm): letzte 60 min. Kommt einmal pro Stunde, ist aber genauer als `Precipitation now`.
- **Precipitation last 24h** („Niederschlag letzte 24h“, mm): gleitend die letzten 24 Stunden
- **Precipitation yesterday** („Niederschlag gestern“, mm): Menge des vorherigen Kalendertags, verfügbar gegen 00:20 Uhr Ortszeit
- **Precipitation total (hourly)** („Niederschlag gesamt (stündlich)“, mm): fortlaufende Summe allen Regens seit der Einrichtung, wächst einmal pro Stunde. Für „Regen diese Woche“ und Automationen am selben Tag
- **Precipitation total (daily)** („Niederschlag gesamt (täglich)“, mm): dasselbe, gebildet aus `Precipitation yesterday`, wächst einmal am Tag. Für Monats- und Jahresstatistiken

**Regenwarnung · jede Minute neu berechnet**

- **Rain warning** („Regenwarnung“): `dry` (Trocken), `soon` (Regen in Kürze) oder `rain` (Regen). Die Details für Benachrichtigungen stehen in den Attributen.
- **Rain warning lead time** („Vorwarnzeit Regenwarnung“, min, Regler): wie früh `soon` gemeldet wird, 5–120 min, Standard 60 min

Das genaue Verhalten jedes Sensors und seine Attribute stehen unter [Entitäten im Detail](#de-entitaeten-im-detail).

## Screenshots

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_config_flow.png" alt="Einrichtungsdialog – Namensfeld und Karte zur Standortauswahl." height="400"/>

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_entities_2026-8-0.png" alt="Geräteseite – die Niederschlagssensoren und ihre aktuellen Werte." height="400"/>

## Installation

### Installation über HACS (empfohlen)

Falls du HACS noch nicht installiert hast, findest du die Anleitung unter https://hacs.xyz.

Um dieses Repository in deiner Home-Assistant-Instanz zu HACS hinzuzufügen, nutze diesen Button:

[![Öffne deine Home-Assistant-Instanz und ein Repository im Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=Integration)

Starte Home Assistant nach der Installation neu. Um DWD Precipitation zu deiner Home-Assistant-Instanz hinzuzufügen, nutze diesen Button:

[![Öffne deine Home-Assistant-Instanz und richte eine neue Integration ein.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dwd_precipitation)

<details>
<summary>Manuelle Installationsschritte</summary>

### Halbmanuelle Installation mit HACS
1. Öffne in HACS den Bereich Integrationen.
2. Klicke oben rechts auf die drei Punkte.
3. Wähle „Benutzerdefinierte Repositories“.
4. Füge die URL des Repositorys hinzu (https://github.com/hoffmann77/ha-dwd-precipitation).
5. Wähle die Kategorie Integration.
6. Klicke auf „HINZUFÜGEN“.
7. Jetzt kannst du die Integration herunterladen.

### Manuelle Installation
1. Lade die ZIP-Datei dieses Repositorys herunter und entpacke sie.
2. Kopiere den Ordner `dwd_precipitation` in das Verzeichnis `/config/custom_components/` deiner Home-Assistant-Installation.

### Home Assistant neu starten
1. Starte Home Assistant neu.

### Integration hinzufügen
1. Öffne **Einstellungen > Geräte & Dienste**.
2. Klicke auf **Integration hinzufügen** und suche nach „DWD Precipitation“.
3. Wähle die Integration DWD Precipitation, um die Einrichtung zu starten.

</details>

## Konfiguration

### Einrichtung

- **Name**: wird für das Gerät und als Präfix jeder Entitäts-ID verwendet. Standard ist der Name deines Home-Assistant-Standorts.
- **Standort**: der Punkt, für den Niederschlag gemeldet wird. Standard ist dein Zuhause in Home Assistant; Standorte außerhalb der Radarabdeckung werden abgelehnt.

### Optionen

Öffne **Einstellungen > Geräte & Dienste > DWD Precipitation > Konfigurieren**. Keine der Optionen beeinflusst, wie oft Daten abgerufen werden.

- **Metadaten als Sensorattribute anzeigen** (Standard: aus): fügt die Quellattribute hinzu, die unter [Attribute](#de-attribute) aufgeführt sind.
- **Sensoren als nicht verfügbar anzeigen, wenn die Daten veraltet sind** (Standard: an): Veröffentlicht der DWD nicht rechtzeitig eine neue Datei, melden die Sensoren `unavailable`, statt den letzten Wert zu behalten. Was „rechtzeitig“ heißt, steht unter [Fehlerbehebung](#de-fehlerbehebung). Die fehlende Datei wird in beiden Fällen weiter abgerufen.
- **Schwelle für Regenerkennung (mm pro Stunde)** (Standard: 0): wie viel vorhergesagter Regen für `Precipitation start`, `Precipitation end` und `Precipitation expected` als Regen zählt. 0 bedeutet jede vom DWD erkannte Menge; etwa 0,5 ignoriert Nieselregen.
- **Anzeige von „Niederschlagsbeginn“ und „Niederschlagsende“** (Standard: Uhrzeit): zeigt eine Uhrzeit oder die Minuten bis zum Ereignis. Die andere Form ist immer als Attribut verfügbar.
- **Wann „Niederschlagsende“ den Regen als beendet ansieht** (Standard: erste trockene Lücke): siehe `Precipitation end` unten.
- **Regenmenge, die den Trockenzähler zurücksetzt (mm)** (Standard: 1,0): `Precipitation now` ab diesem Wert setzt `Timespan without precipitation` zurück.
- **Vergangene Stunde in die stündliche Vorhersagereihe aufnehmen** (Standard: aus): lässt das Attribut `forecast_rolling_1h` von `Peak hourly precipitation next 2h` eine Stunde früher beginnen. Die ersten Einträge enthalten dann auch Regen, der schon gefallen ist, und ein Diagramm zeigt die vergangene Stunde und die Vorhersage als eine durchgehende Kurve. Der Wert des Sensors ändert sich nicht. Verdoppelt etwa die Rechenzeit pro Aktualisierung, was auf kleinen Geräten wie einem Raspberry Pi spürbar sein kann.

Die Umkreis-Sensoren nutzen die **Schwelle für Regenerkennung**, aber mindestens 0,3 mm/h: Weil dort das Maximum über mehrere Zellen genommen wird, würden einzelne Störpixel sonst zu oft anschlagen. Die Regenwarnung hat feste Werte (siehe [Regenwarnung](#de-regenwarnung)) und hängt von keiner Option ab; einstellbar ist nur die Vorwarnzeit über ihren Regler.

<a id="de-entitaeten-im-detail"></a>
## Entitäten im Detail

Für die gesamte vorhergesagte Menge der zwei Stunden addierst du `Precipitation next 1h` und `Precipitation next 1–2h`.

### RADVOR RS: Radar-Nowcast · alle 5 min

- **Precipitation now** (mm): Regen, der in den letzten 60 Minuten gefallen ist. Das ist eine Menge, keine Rate in mm/h. Deckt denselben Zeitraum ab wie `Precipitation last 1h`, wird aber alle 5 Minuten aktualisiert (nur Radar).
- **Precipitation next 1h** (mm): vorhergesagte Menge für die nächsten 0–60 min.
- **Precipitation next 1–2h** (mm): vorhergesagte Menge für 60–120 min ab jetzt.
- **Peak hourly precipitation next 2h** (mm): die größte Regenmenge, die in irgendeinem 60-Minuten-Fenster innerhalb der nächsten 2 h fallen soll, geprüft in 5-Minuten-Schritten. Ein Wolkenbruch, der über die Stundengrenze reicht, erscheint hier vollständig, während `Precipitation next 1h` und `next 1–2h` jeweils nur einen Teil sehen. Das entspricht der Definition der DWD-Starkregenwarnungen (Menge pro Stunde) und eignet sich daher für Warn-Automationen. `0`, wenn kein Regen vorhergesagt ist. Die verglichenen Stunden stehen im Attribut `forecast_rolling_1h`.
- **Timespan without precipitation** (Tage): Zeit, seit `Precipitation now` zuletzt die Rücksetzschwelle erreicht hat. Übersteht Neustarts; Regen während einer Ausfallzeit wird beim Start aus den RADOLAN-Mengen nachgeholt.

### RADVOR RV: Nowcast in 5-Minuten-Schritten · alle 5 min · Horizont 2 h

- **Peak intensity next 1h** (mm/h): stärkste erwartete Regenrate in den nächsten 0–60 min. Unterscheidet Niesel von einem Wolkenbruch; die Menge liefert `Precipitation next 1h`.
- **Peak intensity next 1–2h** (mm/h): dasselbe für 60–120 min ab jetzt.
- **Precipitation start** (Uhrzeit oder min): wann der Regen beginnt. Jetzt bzw. `0`, wenn es schon regnet, `unknown`, wenn innerhalb von 2 h keiner vorhergesagt ist.
- **Precipitation end** (Uhrzeit oder min): wann der Regen aufhört. `unknown`, wenn er über 2 h hinaus anhält; das bedeutet „regnet in 2 Stunden noch“, nicht „nie“.
  - *Erste trockene Lücke*: Ende des aktuellen Schauers. Springt bei Schauerwetter hin und her.
  - *Niederschlag endet innerhalb von 2 h*: wenn innerhalb des Horizonts kein weiterer Regen vorhergesagt ist. Stabiler, bleibt aber länger `unknown`.
- **Precipitation expected** (Binärsensor): `on`, wenn innerhalb der nächsten 2 h Regen vorhergesagt ist.
- **Precipitation start nearby** (Uhrzeit oder min): wie `Precipitation start`, aber für die nasseste Zelle im Umkreis von 1,5 km (die eigene Zelle und ihre acht Nachbarn). Ein Schauer, der ein paar hundert Meter neben dem Standort durchzieht, wird so nicht verpasst. Nutzt dieselbe Anzeigeform (Uhrzeit oder Minuten) wie `Precipitation start`.
- **Nearest precipitation** (km): Entfernung zur nächsten Zelle mit Niederschlag im Umkreis von 5 km, laut der neuesten Analyse. `0`, wenn es am Standort selbst regnet, `unknown`, wenn im Umkreis nichts fällt. Die Attribute `bearing` (Grad, 0 = Norden) und `direction` (N, NE, E, SE, S, SW, W, NW) sagen, wo der Regen ist. Zusammen mit dem Verlauf zeigt der Sensor, ob eine Regenfront näherkommt.

Die Umkreis-Werte kommen aus derselben RV-Datei wie die übrigen RV-Sensoren und kosten keinen zusätzlichen Download.

### HymecNG: Niederschlagsart · alle 5 min

- **Precipitation type**: was gerade fällt. Einer der Werte `no_precipitation`, `not_classified`, `drizzle`, `rain`, `freezing_drizzle`, `freezing_rain`, `sleet`, `snow`, `graupel`, `hail`, `large_hail`.

<a id="de-regenwarnung"></a>
### Regenwarnung · jede Minute

- **Rain warning**: `dry`, `soon` oder `rain`. Grundlage ist die RV-Vorhersage im Umkreis von etwa 1 km in 5-Minuten-Schritten. Der Sensor rechnet bei neuen Daten, bei einer geänderten Vorwarnzeit und zusätzlich jede Minute neu, weil alle Angaben relativ zu „jetzt“ sind.
  - Ein 5-Minuten-Schritt gilt als nass ab **0,3 mm/h**.
  - Ein Regenereignis zählt nur, wenn es **mindestens 10 Minuten** dauert **oder 1,0 mm/h** erreicht. Kürzere, schwache Flecken sind meist Radarrauschen und lösten früher Fehlalarme aus. Ein Ereignis, das bis zum Ende des Vorhersagehorizonts reicht, zählt immer.
  - `rain`: Das erste relevante Ereignis läuft bereits. `soon`: Es beginnt innerhalb der Vorwarnzeit. Sonst `dry`.
  - Die **Niederschlagsart** kommt aus dem Radar (HymecNG): Fällt am Standort schon etwas, gilt dessen Art, sonst die Art des nächsten Niederschlags im 5-km-Umkreis.
  - `unavailable`, solange keine aktuelle RV-Vorhersage vorliegt.
- **Rain warning lead time** (min): Regler von 5 bis 120 min in 5er-Schritten, beim ersten Start 60 min. Der eingestellte Wert übersteht Neustarts. Eine Änderung wirkt sofort auf die Regenwarnung.

### RADOLAN RW / SF: Analyse aus Radar und Regenmessern · stündlich / täglich

- **Precipitation last 1h** (mm): Regen der letzten 60 Minuten. Kommt einmal pro Stunde, ist aber genauer als `Precipitation now`.
- **Precipitation last 24h** (mm): Regen der gleitenden letzten 24 Stunden. Stündlich aktualisiert.
- **Precipitation yesterday** (mm): Menge des vorherigen Kalendertags. Einmal täglich aktualisiert, gegen 00:20 Uhr deutscher Ortszeit.

### Fortlaufende Summen: für Statistiken · stündlich / täglich

Zwei immer weiter wachsende Summen (State-Class `total_increasing`) für die Langzeitstatistik von Home Assistant, die Statistik-Diagrammkarte und den Helfer [Verbrauchszähler (Utility Meter)](https://www.home-assistant.io/integrations/utility_meter/). Nutze sie für tägliche, wöchentliche, monatliche oder jährliche Regensummen; die anderen Sensoren sind Momentaufnahmen und lassen sich über die Zeit nicht korrekt aufsummieren. Beide beginnen bei 0, wenn die Integration eingerichtet wird.

- **Precipitation total (hourly)** (mm): addiert jeden Wert von `Precipitation last 1h` einmal. Innerhalb der Stunde aktuell und daher geeignet für Automationen wie „wie viel Regen seit heute Morgen“.
- **Precipitation total (daily)** (mm): addiert jeden Wert von `Precipitation yesterday` einmal. Der Regen von heute erscheint erst am nächsten Morgen, aber da es nur eine Datei pro Tag gibt, ist das die robusteste Wahl für Monats- und Jahreswerte. An den beiden Tagen der Zeitumstellung liegen die 23:50-Zeitfenster 23 bzw. 25 Stunden auseinander, während jede Datei 24 Stunden abdeckt. Dadurch wird im Frühjahr eine Stunde doppelt gezählt und im Herbst eine ausgelassen.

War Home Assistant offline oder hat der DWD eine Zeit lang nichts veröffentlicht, werden die fehlenden Dateien bei der nächsten Aktualisierung im Hintergrund abgerufen (bis zu 48 Stunden für die stündliche Summe, 7 Tage für die tägliche) und nachträglich addiert. Dateien, die der DWD nicht mehr bereitstellt, bleiben außen vor.

<a id="de-attribute"></a>
### Attribute

Immer vorhanden:

| Attribut | Entitäten | Beschreibung |
|-----------|----------|-------------|
| `minutes_until` / `at` | `Precipitation start`, `Precipitation end`, `Precipitation expected`, `Precipitation start nearby` | Die Form, die *nicht* als Zustand angezeigt wird: ganze Minuten bis zum Ereignis oder dessen Zeitpunkt in ISO-8601 (UTC). Der Binärsensor hat beide, bezogen auf den vorhergesagten Beginn (`null`, wenn kein Regen erwartet wird) |
| `forecast_5min` | `Precipitation expected` | Die vollständige RV-Vorhersage mit 25 Punkten (0–120 min in 5-Minuten-Schritten); jeder Punkt hat `lead`, `start`, `end`, `value` (mm) und `intensity` (mm/h), dazu `intensity_area` (mm/h, nasseste Zelle im Umkreis von 1,5 km) und `nearest_km` (nächster Niederschlag im 5-km-Umkreis, `null` = keiner). Wird nicht im Verlauf gespeichert |
| `window_start` / `window_end` | `Peak hourly precipitation next 2h` | Beginn und Ende der nassesten Stunde in ISO-8601 (UTC); `null`, wenn kein Regen vorhergesagt ist. Bei Gleichstand das frühere Fenster |
| `forecast_rolling_1h` | `Peak hourly precipitation next 2h` | Die stündliche Vorhersagereihe, aus der der Sensor seinen Wert nimmt: ein Eintrag alle 5 Minuten, jeweils die mm Regen in der Stunde von `start` bis `end`. Um 14:00 laufen die Einträge von 14:00–15:00 bis 15:00–16:00 (13 Einträge); der Sensor zeigt den größten. Mit *Vergangene Stunde in die stündliche Vorhersagereihe aufnehmen* beginnt die Reihe eine Stunde früher, bei 13:00–14:00 (25 Einträge); der erste Eintrag entspricht dann `Precipitation now`. `lead` sind die Minuten von jetzt bis `end`. Wird nicht im Verlauf gespeichert |
| `hours_without_precipitation` | `Timespan without precipitation` | Die Trockenphase in Stunden; `null`, bis der Zähler gestartet ist |
| `dry_since` | `Timespan without precipitation` | Zeitpunkt (ISO-8601, UTC) des Regens, der den Zähler zuletzt zurückgesetzt hat |
| `counted_until` | `Precipitation total (hourly)`, `Precipitation total (daily)` | Ende (ISO-8601, UTC) des neuesten DWD-Zeitfensters, das in der Summe enthalten ist |
| `bearing` / `direction` | `Nearest precipitation` | Richtung des nächsten Niederschlags in Grad (0 = Norden, 90 = Osten) und als Himmelsrichtung; `null`, wenn es am Standort selbst regnet |

Beim Sensor **Rain warning**:

| Attribut | Beschreibung |
|-----------|-------------|
| `rain_starts_in_min` | Minuten bis zum Beginn des relevanten Ereignisses (`0`, wenn es schon regnet); `null`, wenn keins vorhergesagt ist |
| `next_length` | Dauer des Ereignisses in Minuten; reicht es über den Horizont, bis zum Horizont gerechnet |
| `next_open_end` | `true`, wenn das Ereignis am Ende des Horizonts noch andauert |
| `current_open_end` / `current_remaining_min` | Bei `rain`: ob das Ende offen ist bzw. in wie vielen Minuten der Regen aufhört |
| `next_peak_intensity` / `next_amount_mm` | Spitzenintensität (mm/h) und Menge (mm) des Ereignisses |
| `next_intensity_level` | Stufe nach DWD: `leicht` (< 2,5 mm/h), `mäßig` (< 10), `stark` (< 50), `sehr stark` |
| `precipitation_type` / `precipitation_type_source` | Niederschlagsart (z. B. `rain`, `snow`) und Herkunft: `radar` (am Standort) oder `radar_nearby` (nächster Niederschlag im Umkreis) |
| `precipitation_type_radar` | Art, die HymecNG genau am Standort meldet |
| `lead_time_min` | aktuell eingestellte Vorwarnzeit |
| `forecast_age_min` / `forecast_remaining_horizon_min` | Alter der Vorhersage und verbleibender Horizont in Minuten. Werden nicht im Verlauf gespeichert |

Mit **Metadaten als Sensorattribute anzeigen** hat jeder DWD-Sensor zusätzlich:

| Attribut | Beschreibung |
|-----------|-------------|
| `source_product` | DWD-Produktkennung aus dem Dateikopf (z. B. `"RADVOR-RS"`, `"RW"`) |
| `source_timestamp` | Bezugszeit der DWD-Datei in UTC. Bei RADVOR die Analysezeit vor dem Vorhersagevorlauf, bei RADOLAN das Ende des Messzeitraums |
| `lead_time_minutes` | Vorhersagevorlauf in Minuten (`0`, `60` oder `120` bei RADVOR, das Ende der nassesten Stunde bei `Peak hourly precipitation next 2h`; `null` bei RADOLAN) |
| `data_start` / `data_end` | Beginn und Ende (ISO-8601, UTC) des Zeitraums, den der Wert abdeckt; `null` bei Werten ohne Zeitraum |

<a id="de-blueprint"></a>
## Blueprint „DWD Regenwarnung“

Der Blueprint macht aus der Regenwarnung eine fertige Automation. Er liegt in diesem Repository unter [`blueprints/automation/dwd/dwd_regenwarnung.yaml`](blueprints/automation/dwd/dwd_regenwarnung.yaml); kopiere die Datei nach `/config/blueprints/automation/dwd/` oder importiere sie über **Einstellungen > Automationen & Szenen > Blueprints > Blueprint importieren** mit der URL der Datei. Lege sie unter **Einstellungen > Automationen & Szenen > Blueprints > DWD Regenwarnung > Automation erstellen** an.

| Eingabe | Standard | Bedeutung |
|---------|----------|-----------|
| Regenwarnung-Sensor | – | der Sensor `Rain warning` dieser Integration |
| Regensensor (optional) | leer | ein Regensensor vor Ort. Meldet die Vorhersage schon Regen, der Sensor aber `dry`, lautet die Meldung „Es kann gleich zu regnen beginnen.“ statt „Es regnet bereits …“ |
| Benachrichtigung | keine | beliebige Aktionen, z. B. `notify.pushover`. Der Text steht in der Variable `{{ message_text }}` |
| Durchsage | keine | Aktionen für Sprachausgabe, z. B. `notify.send_message` an Echo-Geräte, ebenfalls mit `{{ message_text }}` |
| Durchsagen ab / bis | 06:30 / 21:30 | Durchsagen nur in diesem Zeitfenster; Benachrichtigungen kommen immer |
| Trockenzeit bis zum Ende eines Ereignisses | 15 min | so lange muss die Warnung `dry` sein, bevor ein neues Ereignis wieder gemeldet wird |

Pro Regenereignis kommt genau eine Meldung, zum Beispiel „In 20 Minuten beginnt leichter Regen für 35 Minuten.“ oder „Es regnet bereits, noch etwa 20 Minuten.“

<a id="de-fehlerbehebung"></a>
## Fehlerbehebung

**Ein Sensor ist kurz `unavailable` oder das Log meldet, eine DWD-Datei sei nicht gefunden worden.** Der DWD veröffentlicht oft ein paar Minuten zu spät. Die Integration versucht es automatisch erneut, zuerst nach 60 Sekunden und dann in größer werdenden Abständen bis höchstens 5 Minuten (15 Minuten für `Precipitation yesterday`). Ein Sensor wird erst `unavailable`, wenn seine nächste Datei mehr als 6 Minuten überfällig ist (30 Minuten für `Precipitation yesterday`), und erholt sich beim nächsten erfolgreichen Abruf. An deiner Konfiguration liegt es nicht.

**Sensoren bleiben nach der Einrichtung `unavailable`.** Prüfe das Log von Home Assistant auf Fehler und ob `opendata.dwd.de` aus deinem Netzwerk erreichbar ist. Sind nur einige Sensoren betroffen, laufen die anderen DWD-Produkte unabhängig davon weiter.

**`Precipitation type` zeigt `unknown`.** Der Standort liegt außerhalb der HymecNG-Radarabdeckung.

## Datenquelle

Alle Daten stammen vom **DWD (Deutscher Wetterdienst)**:

<img src="docs/assets/dwd-logo.png" alt="Logo des Deutschen Wetterdienstes" width="200"/>

## Lizenz

Diese Integration ist nur dank der großartigen Arbeit der Mitwirkenden am Paket **[wradlib](https://github.com/wradlib/wradlib)** möglich.

Alle Dateien in `custom_components/dwd_precipitation/radar/` stehen unter der [wradlib-Lizenz](custom_components/dwd_precipitation/radar/LICENSE.txt) (MIT).

---

<a id="english-version"></a>
# English version

## DWD Precipitation

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/Hoffmann77/ha-dwd-precipitation)](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
[![Tests](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml)
[![HACS Validate](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml)

Radar-based precipitation measurements and forecasts from the German Weather Service (DWD), for your exact location, directly in Home Assistant.

> [!IMPORTANT]
> This integration **only works** for locations **within Germany** and areas immediately adjacent to the German border.
> The DWD radar composites do not cover other countries.

## Features

- **Location-precise:** values come from the ~1 km radar grid cell containing your coordinates
- **Live:** the nowcast sensors refresh every 5 minutes
- **Two-hour forecast:** forecast totals, peak intensity, and when rain starts and stops
- **Precipitation type:** rain, drizzle, snow, sleet, graupel, hail, freezing rain
- **Measured totals:** past hour, past 24 hours, yesterday, and a days-without-rain counter
- **Long-term totals:** running rain totals for Home Assistant's statistics, so weekly, monthly and yearly sums work out of the box
- **Customizable thresholds** for rain events to use as input for automations.
- **Neighbourhood evaluation**: rain just next to your own cell is no longer missed; the nearest precipitation within 5 km is reported with distance and compass direction
- **Rain warning**: a ready-made `dry` / `soon` / `rain` warning sensor with adjustable lead time and a noise filter against false alarms, plus a blueprint for notifications

## Entities

All entities belong to one **DWD Precipitation** device per configured location.

Names ending in **`last <N>`** are measured totals over the window ending now.

Names ending in **`next <N>`** are forecasts. 

> [!NOTE]
> **`next 1–2h`** is the *second* hour ahead (60–120 min), not the coming two hours.

**RADVOR RS: radar nowcast · updated every 5 min**

- **Precipitation now** (mm): rain that fell in the past 60 minutes. This is a total, not a mm/h rate.
- **Precipitation next 1h** (mm): forecast total for the next 0–60 min
- **Precipitation next 1–2h** (mm): forecast total for 60–120 min from now
- **Peak hourly precipitation next 2h** (mm): the wettest 60-minute window forecast within the next 2 h
- **Timespan without precipitation** (days): time since `Precipitation now` last reached the reset threshold.

**RADVOR RV: nowcast in 5-min steps · updated every 5 min**

- **Peak intensity next 1h** (mm/h): heaviest expected rain rate in the next 0–60 min
- **Peak intensity next 1–2h** (mm/h): the same for 60–120 min
- **Precipitation start** (time or min): when rain begins; `unknown` if none within 2 h
- **Precipitation end** (time or min): when rain stops; `unknown` if it lasts beyond 2 h
- **Precipitation expected** (binary sensor): `on` if rain is forecast within 2 h
- **Precipitation start nearby** (time or min): when rain begins within about 1 km; `unknown` if none within 2 h
- **Nearest precipitation** (km): distance to the nearest precipitation within 5 km, with the compass direction as an attribute; `unknown` if nothing is falling nearby

**HymecNG: precipitation type · updated every 5 min**

- **Precipitation type**: what is falling right now: rain, drizzle, snow, sleet, graupel, hail, freezing rain, …

**RADOLAN RW / SF: radar + rain-gauge analysis · updated hourly / daily**

- **Precipitation last 1h** (mm): past 60 min. Arrives once an hour but is more accurate than `Precipitation now`.
- **Precipitation last 24h** (mm): rolling past 24 hours
- **Precipitation yesterday** (mm): the previous calendar day's total, available around 00:20 local time
- **Precipitation total (hourly)** (mm): running total of all rain since setup, grows once an hour. For "rain this week" and same-day automations
- **Precipitation total (daily)** (mm): the same, built from `Precipitation yesterday`, grows once a day. For monthly and yearly statistics

**Rain warning · re-evaluated every minute**

- **Rain warning**: `dry`, `soon` or `rain`. The details for notifications are in the attributes.
- **Rain warning lead time** (min, slider): how early `soon` is reported, 5–120 min, default 60 min

See [Entity details](#entity-details) for the full behaviour of each sensor and its attributes.

## Screenshots

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_config_flow.png" alt="Setup dialog — name field and location selector map." height="400"/>

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_entities_2026-8-0.png" alt="Device page — the precipitation sensors and their current values." height="400"/>

## Installation

### Install using HACS (recommended)

If you do not have HACS installed yet, visit https://hacs.xyz for installation instructions.

To add this repository to HACS in your Home Assistant instance, use this button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=Integration)

After installation, restart Home Assistant. To add DWD Precipitation to your Home Assistant instance, use this button:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dwd_precipitation)

<details>
<summary>Manual installation steps</summary>

### Semi-manual installation with HACS
1. Go to the HACS integrations section.
2. Click the 3 dots in the top right corner.
3. Select "Custom repositories".
4. Add the URL (https://github.com/hoffmann77/ha-dwd-precipitation) of the repository.
5. Select the integration category.
6. Click the "ADD" button.
7. Now you are able to download the integration.

### Manual installation
1. Download the ZIP file of this repository and extract its contents.
2. Copy the `dwd_precipitation` folder into `/config/custom_components/` in your Home Assistant directory.

### Restart Home Assistant
1. Restart your Home Assistant.

### Add the integration
1. Navigate to **Settings > Devices & Services**.
2. Click **Add Integration** and search for "DWD Precipitation".
3. Select the DWD Precipitation integration to start setup.

</details>

## Configuration

### Setup

- **Name**: used for the device and as the prefix of every entity id. Defaults to your Home Assistant location name.
- **Location**: the point to report precipitation for. Defaults to your Home Assistant home location; locations outside the radar coverage are rejected.

### Options

Open **Settings > Devices & Services > DWD Precipitation > Configure**. None of the options affect how often data is fetched.

- **Add technical details to each sensor:**(default: off): adds the source attributes listed under [Attributes](#attributes).
- **Show sensors as unavailable when the data is out of date** (default: on): if DWD does not publish a new file in time, sensors report `unavailable` instead of keeping the last value. See [Troubleshooting](#troubleshooting) for how long "in time" is. The missing file keeps being retried either way.
- **Rain detection threshold (mm per hour)** (default: 0): how much forecast rain counts as rain for `Precipitation start`, `Precipitation end` and `Precipitation expected`. 0 means any amount DWD detects; around 0.5 ignores drizzle.
- **How "Precipitation start" and "Precipitation end" report** (default: clock time): show a clock time or the minutes until the event. The other form is always available as an attribute.
- **When "Precipitation end" counts rain as over** (default: first dry gap): see `Precipitation end` below.
- **Rain needed to reset the dry-streak counter (mm)** (default: 1.0): `Precipitation now` at or above this value resets `Timespan without precipitation`.
- **Include the past hour in the hourly forecast series** (default: off): makes the `forecast_rolling_1h` attribute of `Peak hourly precipitation next 2h` start one hour earlier, so the first entries also include rain that has already fallen and a chart shows the past hour and the forecast as one curve. The sensor's value does not change. Roughly doubles the processing time per update, which can matter on small devices such as a Raspberry Pi.

The neighbourhood sensors use the **Rain detection threshold**, but at least 0.3 mm/h: because they take the maximum over several cells, single noisy pixels would trigger them too often otherwise. The rain warning uses fixed values (see [Rain warning](#rain-warning)) and does not depend on any option; only its lead time is adjustable, through its slider.

## Entity details

For the full two-hour forecast total, add `Precipitation next 1h` and `Precipitation next 1–2h`.

### RADVOR RS: radar nowcast · every 5 min

- **Precipitation now** (mm): rain that fell in the past 60 minutes. This is a total, not a mm/h rate. It covers the same window as `Precipitation last 1h` but updates every 5 minutes (radar only).
- **Precipitation next 1h** (mm): forecast total for the next 0–60 min.
- **Precipitation next 1–2h** (mm): forecast total for 60–120 min from now.
- **Peak hourly precipitation next 2h** (mm): the most rain forecast to fall in any 60-minute window within the next 2 h, checked in 5-minute steps. A downpour that straddles the one-hour mark shows here in full, where `Precipitation next 1h` and `next 1–2h` each only see part of it. This matches how DWD's heavy-rain warnings are defined (amount per hour), so it suits alert automations. `0` when no rain is forecast. The hours it compares are listed in the `forecast_rolling_1h` attribute.
- **Timespan without precipitation** (days): time since `Precipitation now` last reached the reset threshold. Survives restarts; rain during downtime is caught up from the RADOLAN totals on startup.

### RADVOR RV: nowcast in 5-min steps · every 5 min · 2 h horizon

- **Peak intensity next 1h** (mm/h): heaviest expected rain rate in the next 0–60 min. Tells drizzle from a downpour; `Precipitation next 1h` gives the amount.
- **Peak intensity next 1–2h** (mm/h): the same for 60–120 min from now.
- **Precipitation start** (time or min): when rain begins. Now / `0` if it is already raining, `unknown` if none is forecast within 2 h.
- **Precipitation end** (time or min): when rain stops. `unknown` if it continues beyond 2 h, which means "still raining in 2 hours", not "never".
  - *First dry gap*: end of the current burst. Moves around during showers.
  - *Precipitation clears within 2 h*: when no more rain is forecast within the horizon. Steadier, but stays `unknown` longer.
- **Precipitation expected** (binary sensor): `on` if rain is forecast within the next 2 h.
- **Precipitation start nearby** (time or min): like `Precipitation start`, but for the wettest cell within 1.5 km (your own cell and its eight neighbours). A shower passing a few hundred metres from your location is no longer missed. Uses the same display form (time or minutes) as `Precipitation start`.
- **Nearest precipitation** (km): distance to the nearest cell with precipitation within 5 km, according to the latest analysis. `0` when it is raining at the location itself, `unknown` when nothing is falling nearby. The `bearing` (degrees, 0 = north) and `direction` (N, NE, E, SE, S, SW, W, NW) attributes tell where the rain is. Together with its history the sensor shows whether a rain front is approaching.

The neighbourhood values come from the same RV file as the other RV sensors and need no extra download.

### HymecNG: precipitation type · every 5 min

- **Precipitation type**: what is falling right now. One of `no_precipitation`, `not_classified`, `drizzle`, `rain`, `freezing_drizzle`, `freezing_rain`, `sleet`, `snow`, `graupel`, `hail`, `large_hail`.

<a id="rain-warning"></a>
### Rain warning · every minute

- **Rain warning**: `dry`, `soon` or `rain`. Based on the RV forecast within about 1 km in 5-minute steps. The sensor re-evaluates on new data, on a changed lead time and additionally every minute, because every value is relative to "now".
  - A 5-minute step counts as wet from **0.3 mm/h**.
  - A rain event only counts if it lasts **at least 10 minutes** **or reaches 1.0 mm/h**. Shorter, faint specks are usually radar noise and used to cause false alarms. An event that reaches the end of the forecast horizon always counts.
  - `rain`: the first relevant event is already under way. `soon`: it starts within the lead time. Otherwise `dry`.
  - The **precipitation type** comes from the radar (HymecNG): if something is already falling at the location, its type is used, otherwise the type of the nearest precipitation within 5 km.
  - `unavailable` while no current RV forecast is available.
- **Rain warning lead time** (min): slider from 5 to 120 min in steps of 5, 60 min on first start. The value survives restarts. A change takes effect on the rain warning immediately.

### RADOLAN RW / SF: radar + rain-gauge analysis · hourly / daily

- **Precipitation last 1h** (mm): rain that fell in the past 60 minutes. Arrives once an hour, but is more accurate than `Precipitation now`.
- **Precipitation last 24h** (mm): rain that fell in the rolling past 24 hours. Updated hourly.
- **Precipitation yesterday** (mm): total for the previous calendar day. Updated once a day, around 00:20 German local time.

### Running totals: for statistics · hourly / daily

Two ever-growing totals (state class `total_increasing`), for Home Assistant's long-term statistics, the statistics graph card, and the [Utility Meter](https://www.home-assistant.io/integrations/utility_meter/) helper. Use them for daily, weekly, monthly or yearly rain sums; the other sensors are snapshots and do not add up correctly over time. Both start at 0 when the integration is set up.

- **Precipitation total (hourly)** (mm): adds each `Precipitation last 1h` value once. Up to date within the hour, so it suits "how much rain since this morning" automations.
- **Precipitation total (daily)** (mm): adds each `Precipitation yesterday` value once. Today's rain only appears the next morning, but a single file a day makes it the most robust choice for monthly and yearly figures. On the two DST changeover days the 23:50 windows are 23 or 25 hours apart while each file covers 24 hours, so one hour is counted twice in spring and missed in autumn.

If Home Assistant was offline, or DWD failed to publish for a while, the missed files are fetched in the background on the next update (up to 48 hours for the hourly total, 7 days for the daily one) and added late. Files DWD no longer serves are left out.

### Attributes

Always present:

| Attribute | Entities | Description |
|-----------|----------|-------------|
| `minutes_until` / `at` | `Precipitation start`, `Precipitation end`, `Precipitation expected`, `Precipitation start nearby` | The form *not* shown as the state: whole minutes until the event, or its ISO-8601 UTC time. The binary sensor carries both, pointing at the forecast start (`null` when no rain is expected) |
| `forecast_5min` | `Precipitation expected` | The full 25-point RV forecast (0–120 min in 5-minute steps); each point has `lead`, `start`, `end`, `value` (mm) and `intensity` (mm/h), plus `intensity_area` (mm/h, wettest cell within 1.5 km) and `nearest_km` (nearest precipitation within 5 km, `null` = none). Not recorded in history |
| `window_start` / `window_end` | `Peak hourly precipitation next 2h` | ISO-8601 UTC start and end of the wettest hour; `null` when no rain is forecast. If two windows tie, the earlier one |
| `forecast_rolling_1h` | `Peak hourly precipitation next 2h` | The hourly forecast series the sensor picks its value from: one entry every 5 minutes, each the mm of rain in the hour from `start` to `end`. At 14:00 the entries run from 14:00–15:00 to 15:00–16:00 (13 entries); the sensor shows the largest. With *Include the past hour in the hourly forecast series* on, the series starts one hour earlier, at 13:00–14:00 (25 entries); the first entry then equals `Precipitation now`. `lead` is the minutes from now to `end`. Not recorded in history |
| `hours_without_precipitation` | `Timespan without precipitation` | The dry streak in hours; `null` until the counter has started |
| `dry_since` | `Timespan without precipitation` | ISO-8601 UTC time of the rain that last reset the counter |
| `counted_until` | `Precipitation total (hourly)`, `Precipitation total (daily)` | ISO-8601 UTC end of the newest DWD window included in the total |
| `bearing` / `direction` | `Nearest precipitation` | Direction of the nearest precipitation in degrees (0 = north, 90 = east) and as a compass point; `null` when it is raining at the location itself |

On the **Rain warning** sensor:

| Attribute | Description |
|-----------|-------------|
| `rain_starts_in_min` | Minutes until the relevant event starts (`0` when already raining); `null` if none is forecast |
| `next_length` | Event duration in minutes; if it runs past the horizon, counted up to the horizon |
| `next_open_end` | `true` if the event is still going on at the end of the horizon |
| `current_open_end` / `current_remaining_min` | When `rain`: whether the end is open, or in how many minutes the rain stops |
| `next_peak_intensity` / `next_amount_mm` | Peak intensity (mm/h) and amount (mm) of the event |
| `next_intensity_level` | DWD level, in German: `leicht` (light, < 2.5 mm/h), `mäßig` (moderate, < 10), `stark` (heavy, < 50), `sehr stark` (very heavy) |
| `precipitation_type` / `precipitation_type_source` | Precipitation type (e.g. `rain`, `snow`) and its source: `radar` (at the location) or `radar_nearby` (nearest precipitation around it) |
| `precipitation_type_radar` | Type HymecNG reports exactly at the location |
| `lead_time_min` | Currently set lead time |
| `forecast_age_min` / `forecast_remaining_horizon_min` | Age of the forecast and remaining horizon in minutes. Not recorded in history |

With **Add technical details to each sensor** enabled, every DWD sensor also has:

| Attribute | Description |
|-----------|-------------|
| `source_product` | DWD product identifier from the file header (e.g. `"RADVOR-RS"`, `"RW"`) |
| `source_timestamp` | UTC reference time of the DWD file. For RADVOR, the analysis time before the forecast lead; for RADOLAN, the end of the measurement window |
| `lead_time_minutes` | Forecast lead in minutes (`0`, `60` or `120` for RADVOR, the end of the wettest hour for `Peak hourly precipitation next 2h`; `null` for RADOLAN) |
| `data_start` / `data_end` | ISO-8601 UTC start and end of the period the value covers; `null` for values without a period |

## Blueprint "DWD rain warning"

The blueprint turns the rain warning into a ready-made automation. It lives in this repository at [`blueprints/automation/dwd/dwd_regenwarnung.yaml`](blueprints/automation/dwd/dwd_regenwarnung.yaml); copy the file to `/config/blueprints/automation/dwd/` or import it under **Settings > Automations & Scenes > Blueprints > Import blueprint** with the file's URL. Then create it under **Settings > Automations & Scenes > Blueprints > DWD Regenwarnung > Create automation**. The blueprint's input names and messages are in German.

| Input | Default | Meaning |
|-------|---------|---------|
| Regenwarnung-Sensor (rain warning sensor) | – | this integration's `Rain warning` sensor |
| Regensensor (rain sensor, optional) | empty | a local rain sensor. If the forecast already says rain but the sensor reports `dry`, the message reads "Es kann gleich zu regnen beginnen." ("It may start raining any moment.") instead of "Es regnet bereits …" ("It is already raining …") |
| Benachrichtigung (notification) | none | any actions, e.g. `notify.pushover`. The text is in the `{{ message_text }}` variable |
| Durchsage (announcement) | none | actions for voice output, e.g. `notify.send_message` to Echo devices, also with `{{ message_text }}` |
| Durchsagen ab / bis (announcements from / until) | 06:30 / 21:30 | announcements only within this window; notifications are always sent |
| Trockenzeit (dry time until an event ends) | 15 min | how long the warning must be `dry` before a new event is reported again |

Exactly one message is sent per rain event, for example "In 20 Minuten beginnt leichter Regen für 35 Minuten." ("Light rain starts in 20 minutes for 35 minutes.") or "Es regnet bereits, noch etwa 20 Minuten." ("It is already raining, about 20 more minutes.").

## Troubleshooting

**A sensor is briefly `unavailable`, or the log says a DWD file was not found.** DWD often publishes a few minutes late. The integration retries automatically, starting after 60 seconds and backing off to at most 5 minutes (15 minutes for `Precipitation yesterday`). A sensor only turns `unavailable` once its next file is more than 6 minutes overdue (30 minutes for `Precipitation yesterday`), and recovers on the next successful fetch. Your configuration is not at fault.

**Sensors stay `unavailable` after setup.** Check the Home Assistant log for errors and verify that `opendata.dwd.de` is reachable from your network. If only some sensors are affected, the other DWD products keep working independently.

**`Precipitation type` shows `unknown`.** The location is outside the HymecNG radar coverage.

## Data source

All data is derived from the **DWD (Deutscher Wetterdienst)**:

<img src="docs/assets/dwd-logo.png" alt="Deutscher Wetterdienst Logo" width="200"/>

## License

This integration is only possible thanks to the great work done by the contributors of the **[wradlib](https://github.com/wradlib/wradlib)** package.

All files in `custom_components/dwd_precipitation/radar/` are licensed under the [wradlib license](custom_components/dwd_precipitation/radar/LICENSE.txt) (MIT).
