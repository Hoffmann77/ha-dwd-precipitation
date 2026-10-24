---
title: Konfiguration
description: Einen Standort einrichten und die Optionen von DWD Precipitation wählen.
---

## Einrichtung {#setup}

Wenn du die Integration hinzufügst, fragt sie nach zwei Dingen:

![Einrichtungsdialog mit dem Namensfeld und der Standortkarte](/screenshot_config_flow.png)

- **Name:** Er wird für das Gerät und als Präfix jeder Entitäts-ID verwendet.
  Voreingestellt ist der Name deines Home-Assistant-Standorts. Mit dem Namen
  `Home` heißen die Entitäten `sensor.home_precipitation_last_60_min` und so
  weiter.
- **Standort:** der Punkt, für den Niederschlag gemeldet wird. Voreingestellt
  ist der Heimatstandort deines Home Assistant. Die Sensoren melden die
  Gitterzelle des Radars, die diesen Punkt enthält, etwa 1 km breit.

Ein Standort deutlich außerhalb Deutschlands wird sofort abgelehnt. Einer nahe
dem Rand der Radarabdeckung wird angenommen, und falls ein Produkt ihn doch
nicht abdeckt, meldet das Log das, wenn dieses Produkt gelesen wird. Siehe
[Gitterzellen-Suche](../how-it-works/grid-lookup.md).

### Mehrere Standorte {#several-locations}

Füge die Integration einmal pro Standort hinzu, zum Beispiel für dein Zuhause
und deine Ferienwohnung. Jeder Eintrag bekommt sein eigenes Gerät und seinen
eigenen Satz Entitäten, daher braucht jeder einen anderen Namen.

Um einen bestehenden Eintrag an einen anderen Standort zu verlegen, lösche ihn
und füge ihn neu hinzu.

### Regenwarnungen {#rain-warnings}

Ein Standort kann eigene Regenwarnungen haben, etwa „Wäsche, 60 Minuten
vorher“. Füge eine mit **Regenwarnung hinzufügen** am Eintrag des Standorts
unter **Einstellungen > Geräte & Dienste > DWD Precipitation** hinzu. Jede
Warnung ist ein Gerät mit einer An/Aus- und einer Status-Entität; siehe
[Regenwarnungen](../entities/rain-warnings.md).

## Optionen {#options}

Öffne **Einstellungen > Geräte & Dienste > DWD Precipitation >
Konfigurieren**. Das Formular hat einen Abschnitt für jede Gruppe von
Sensoren, und der Hilfetext jeder Einstellung verlinkt auf ihre Beschreibung
auf dieser Seite. Beim Speichern wird die Integration neu geladen; die
Sensoren sind nach wenigen Sekunden wieder da.

Keine der Einstellungen ändert, wie oft Daten abgerufen werden: Jedes Produkt
wird abgerufen, sobald der DWD es veröffentlicht, und ein fehlgeschlagener
Download wird automatisch wiederholt.

| Abschnitt | Einstellung | Standard |
|-----------|-------------|----------|
| [Regenvorhersage](#rain-forecast) | [Nur Regen zählen, der stärker ist als](#rain-detection-threshold) | 0 mm/h |
| | [Beginn und Ende anzeigen als](#start-and-end-format) | Uhrzeit |
| | [„Niederschlagsende“ zeigt](#end-algorithm) | die erste trockene Pause |
| [Zeitraum ohne Niederschlag](#timespan-without-precipitation) | [Regen, der die Zählung zurücksetzt](#dry-streak-threshold) | 1,0 mm |
| | [Gemessen mit](#dry-streak-source) | Radar und Regenmessern (RW) |
| [Regenereignisse und Regenwarnungen](#rain-events-and-rain-warnings) | [Sensor „Regenereignisse“ hinzufügen](#track-rain-events) | aus |
| | [Nur Regen zählen, der stärker ist als](#rain-event-threshold) | 0,1 mm/h |
| [Erweitert](#advanced-options) | [Technische Details zu den Sensoren hinzufügen](#technical-details) | aus |
| | [Vergangene Stunde in die stündliche Regenreihe aufnehmen](#past-hour-in-the-series) | aus |
| | [„Nicht verfügbar“ anzeigen, wenn die Daten veraltet sind](#unavailable-when-out-of-date) | an |

## Regenvorhersage {#rain-forecast}

Einstellungen für `Niederschlagsbeginn`, `Niederschlagsende` und
`Niederschlag erwartet`. Die anderen Sensoren melden immer, was der DWD
meldet, egal was du hier einstellst.

### Nur Regen zählen, der stärker ist als {#rain-detection-threshold}

Schwächerer Regen, in mm pro Stunde, gilt für die drei Sensoren als trocken.
`0` (der Standard) zählt jeden Regen, den das Radar sieht; mit etwa `0,5`
wird Nieselregen ignoriert.

### Beginn und Ende anzeigen als {#start-and-end-format}

- **Uhrzeit** (Standard): Die Sensoren zeigen eine Uhrzeit, zum Beispiel
  `14:25`.
- **Minuten ab jetzt**: Die Sensoren zeigen, wie viele Minuten es noch sind,
  zum Beispiel `20`.

Die Form, die du nicht wählst, findest du weiterhin als Attribut am selben
Sensor (`at` oder `minutes_until`).

### „Niederschlagsende“ zeigt {#end-algorithm}

- **Die erste trockene Pause** (Standard): wann der aktuelle Schauer
  aufhört. Bei Schauerwetter verschiebt sich das, weil der nächste Schauer
  nicht mitzählt.
- **Ab wann kein Regen mehr vorhergesagt ist:** wann die Vorhersage
  überhaupt keinen weiteren Regen mehr zeigt. Das ändert sich seltener,
  bleibt aber länger `unknown` („Unbekannt“).

Die Vorhersage des DWD reicht nur zwei Stunden weit. Dauert der Regen länger,
ist der Sensor in beiden Fällen `unknown`.

## Zeitraum ohne Niederschlag {#timespan-without-precipitation}

Einstellungen für [`Zeitraum ohne Niederschlag`](../entities/dry-streak.md),
den Sensor, der zählt, wie lange es nicht geregnet hat.

### Regen, der die Zählung zurücksetzt {#dry-streak-threshold}

Fällt innerhalb einer Stunde mindestens so viel Regen, beginnt die Zählung
wieder bei null. Der Standard ist `1,0` mm; 1 mm sind 1 Liter Wasser pro
Quadratmeter. Es ist eine Menge innerhalb der Stunde, keine Rate.

### Gemessen mit {#dry-streak-source}

Welche Messung des Regens der vergangenen Stunde mit dieser Menge verglichen
wird:

- **Radar und Regenmessern (RW)**, der Standard für neue Installationen: Der
  DWD gleicht das Radar mit Regenmessern am Boden ab, das macht die Messung
  genauer. Der DWD rechnet sie alle 10 Minuten neu, daher zeigt sich ein
  Zurücksetzen etwa 30 bis 40 Minuten nach dem Regen.
- **Nur Radar (RS):** alle 5 Minuten aktualisiert, reagiert also schneller,
  ist aber ungenauer und setzt die Zählung bis zu eine Stunde nach dem Ende
  des Regens immer wieder zurück.

Installationen, die vor dieser Einstellung eingerichtet wurden, behalten
**Nur Radar**, ein Update ändert also nichts; stelle hier um, wenn du die
andere Messung bevorzugst. Die Zählung behält beim Umstellen ihren Wert.

## Regenereignisse und Regenwarnungen {#rain-events-and-rain-warnings}

Regenereignisse verfolgen jeden Schauer von der ersten Vorhersage, die ihn
zeigt, bis er vorbei ist. Darauf bauen die
[Regenwarnungen](../entities/rain-warnings.md) auf; die fügst du auf der Seite
der Integration mit **Regenwarnung hinzufügen** hinzu (siehe
[Regenwarnungen](#rain-warnings) oben). Der Abschnitt ist aufgeklappt, wenn
der Sensor `Regenereignisse` an ist oder der Standort eine Regenwarnung hat,
sonst eingeklappt.

### Sensor „Regenereignisse“ hinzufügen {#track-rain-events}

Fügt den Sensor [`Regenereignisse`](../entities/rain-events.md) hinzu, für
Blueprints, die vor Regen warnen oder darüber berichten. Standardmäßig aus.
Regenwarnungen funktionieren auch ohne ihn.

Solange der Sensor an ist oder der Standort eine Regenwarnung hat, lädt die
Integration auch die Teile der Radardaten nach, die sie verpasst hat (etwa
während eines Neustarts von Home Assistant), und speichert eine kleine
Aufzeichnung des jüngsten Regens auf der Festplatte. Ausschalten entfernt den
Sensor; die Aufzeichnung wird gelöscht, sobald auch keine Regenwarnung sie
mehr braucht, sodass ein erneutes Einschalten dann frisch beginnt.

### Nur Regen zählen, der stärker ist als {#rain-event-threshold}

Schwächerer Regen, in mm pro Stunde, zählt nicht zu einem Regenereignis, für
den Sensor `Regenereignisse` und alle Regenwarnungen. `0` zählt jeden Regen,
den das Radar sieht; der Standard ist `0,1`. Die Einstellung ist unabhängig
von der gleichnamigen unter [Regenvorhersage](#rain-detection-threshold),
daher können die beiden voneinander abweichen, wenn du sie unterschiedlich
einstellst.

## Erweitert {#advanced-options}

Zusätzliche Angaben für Templates und Diagramme, und was die Sensoren zeigen,
wenn der DWD sich verspätet. Der Abschnitt ist eingeklappt; die meisten
Installationen ändern hier nie etwas.

### Technische Details zu den Sensoren hinzufügen {#technical-details}

Zeigt als zusätzliche Attribute der Sensoren, aus welchem DWD-Produkt ein
Wert stammt, wann er gemessen wurde und welchen Zeitraum er abdeckt.
Hilfreich in Templates oder wenn du ein Problem meldest; lass es sonst aus.
[Attribute](../entities/attributes.md#technical-details) listet sie auf.

### Vergangene Stunde in die stündliche Regenreihe aufnehmen {#past-hour-in-the-series}

Für Diagramme: Das Attribut `forecast_rolling_1h` von `Maximaler
Stundenniederschlag nächste 120 min` beginnt dann eine Stunde früher. Seine
ersten Einträge enthalten Regen, der schon gefallen ist, sodass ein Diagramm
die vergangene Stunde und die Vorhersage als eine Kurve zeigt. Der Wert des
Sensors ändert sich nicht.

Die vergangene Stunde wird aus Radardaten berechnet, die die Integration
ohnehin schon geladen hat, und kostet keinen zusätzlichen Download. Nach einem
Neustart, oder wenn der DWD mit einer 5-Minuten-Aktualisierung zu spät war,
erscheint sie, sobald die Integration wieder eine volle Stunde an
Aktualisierungen gesehen hat. Siehe
[RADVOR-RV-Nowcast](../entities/radvor-rv.md#peak-hourly-precipitation).

### „Nicht verfügbar“ anzeigen, wenn die Daten veraltet sind {#unavailable-when-out-of-date}

Verspätet sich der DWD mit neuen Daten, zeigen die betroffenen Sensoren
`unavailable` („Nicht verfügbar“) statt eines alten Werts. Schalte es aus, um
weiter den letzten Wert zu zeigen, auch wenn er Stunden alt ist. In beiden
Fällen werden die fehlenden Daten im Hintergrund weiter abgerufen. Wie spät
zu spät ist, erklärt
[Verfügbarkeit und Aktualität](../how-it-works/availability.md).
