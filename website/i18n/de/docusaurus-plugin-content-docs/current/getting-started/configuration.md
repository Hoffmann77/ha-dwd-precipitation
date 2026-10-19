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

## Optionen {#options}

Öffne **Einstellungen > Geräte & Dienste > DWD Precipitation >
Konfigurieren**. Das Speichern der Optionen lädt die Integration neu; die
Werte sind innerhalb weniger Sekunden wieder da.

Keine der Optionen ändert, wie oft Daten abgerufen werden: Jedes Produkt wird
aktualisiert, sobald der DWD es veröffentlicht, und fehlgeschlagene Abrufe
werden automatisch wiederholt.

| Option | Standard | Betrifft |
|--------|----------|----------|
| [Metadaten als Sensorattribute anzeigen](#technical-details) | aus | Attribute der meisten Sensoren |
| [Schwelle für Regenerkennung](#rain-detection-threshold) | 0 mm/h | Niederschlagsbeginn, -ende, Niederschlag erwartet |
| [Anzeige von „Niederschlagsbeginn“ und „Niederschlagsende“](#start-and-end-format) | Uhrzeit | Niederschlagsbeginn, -ende |
| [Regenmenge, die den Trockenzähler zurücksetzt](#dry-streak-threshold) | 1,0 mm | Zeitraum ohne Niederschlag |
| [Produkt, das den Trockenzähler zurücksetzt](#dry-streak-source) | angeeichte Stunde (RW) | Zeitraum ohne Niederschlag |

### Technische Details {#technical-details}

**Metadaten als Sensorattribute anzeigen** hängt den Namen des DWD-Produkts,
die Messzeit und den Zeitraum, den jeder Wert abdeckt, als Attribute an die
Sensoren an. Das ist nützlich in Templates oder wenn du ein Problem meldest;
lass es sonst aus. [Attribute](../entities/attributes.md#technical-details)
listet sie auf.

### Schwelle für Regenerkennung {#rain-detection-threshold}

**Schwelle für Regenerkennung (mm pro Stunde)** legt fest, ab welcher
vorhergesagten Regenmenge `Niederschlagsbeginn`, `Niederschlagsende` und
`Niederschlag erwartet` von Regen ausgehen. `0` bedeutet jede Menge, die der
DWD erkennt; erhöhe den Wert auf etwa 0,5, um Nieselregen zu ignorieren.

Die anderen Sensoren melden immer, was der DWD meldet, unabhängig von diesem
Schwellwert.

### Format von Beginn und Ende {#start-and-end-format}

**Anzeige von „Niederschlagsbeginn“ und „Niederschlagsende“** wählt zwischen:

- **Uhrzeit** (Standard): Die Sensoren sind Zeitstempel, zum Beispiel `14:25`.
- **Minuten ab jetzt**: Die Sensoren sind Dauern in Minuten, zum Beispiel
  `20`.

Die Form, die du nicht wählst, bleibt als Attribut am selben Sensor verfügbar
(`at` oder `minutes_until`).

### Schwellwert des Trockenzählers {#dry-streak-threshold}

**Regenmenge, die den Trockenzähler zurücksetzt (mm)** legt fest, wie viel
Regen `Zeitraum ohne Niederschlag` auf null zurücksetzt. Verglichen wird mit
der Summe der vergangenen Stunde des gewählten Produkts, in Millimetern über
diese Stunde aufsummiert: `1` bedeutet, dass innerhalb der Stunde 1 mm
gefallen ist, keine Rate.

### Quelle des Trockenzählers {#dry-streak-source}

**Produkt, das den Trockenzähler zurücksetzt** wählt, welche Summe der
vergangenen Stunde `Zeitraum ohne Niederschlag` mit dem Schwellwert
vergleicht:

- **Angeeichte Stunde (RW, alle 10 Minuten)**, der Standard für neue
  Installationen: mit Daten von Niederschlagsmessern angeeicht und genauer.
  Der DWD rechnet diese Analyse der letzten 60 Minuten alle 10 Minuten neu,
  daher zeigt sich ein Zurücksetzen etwa 30 bis 40 Minuten nach dem Regen.
- **Niederschlag letzte 60 min (Radar, RS):** nur Radar und alle 5 Minuten
  aktualisiert. Schneller, aber unruhiger, und seine gleitende Stunde setzt den
  Zähler bis zu eine Stunde nach dem Ende des Regens immer wieder zurück.

Installationen, die vor dieser Option eingerichtet wurden, behalten
`Niederschlag letzte 60 min`, ein Update ändert also nichts; stelle hier um,
wenn du RW bevorzugst. Der Zähler behält beim Umstellen seinen Wert. Siehe
[Zeitraum ohne Niederschlag](../entities/dry-streak.md).

## Erweiterte Optionen {#advanced-options}

Der Abschnitt **Erweiterte Optionen** ist unten im Formular eingeklappt. Die
meisten Installationen brauchen ihn nie.

| Option | Standard | Betrifft |
|--------|----------|----------|
| [Regenereignisse verfolgen](#track-rain-events) | aus | fügt den Sensor Regenereignisse hinzu |
| [Schwelle für Regenereignisse](#rain-event-threshold) | 0,1 mm/h | Regenereignisse |
| [Wann „Niederschlagsende“ den Regen als beendet ansieht](#end-algorithm) | Erste trockene Lücke | Niederschlagsende |
| [Vergangene Stunde in die stündliche Vorhersagereihe aufnehmen](#past-hour-in-the-series) | aus | ein Attribut von Maximaler Stundenniederschlag nächste 120 min |
| [Sensoren als nicht verfügbar anzeigen, wenn die Daten veraltet sind](#unavailable-when-out-of-date) | an | Verfügbarkeit der Sensoren |

### Regenereignisse verfolgen {#track-rain-events}

**Regenereignisse verfolgen** fügt den Sensor
[`Regenereignisse`](../entities/rain-events.md) hinzu. Er verfolgt jeden
Regenschauer von der ersten Vorhersage, die ihn zeigt, bis er gefallen ist,
für Blueprints, die vor Regen warnen oder über Regen berichten.

Ist die Option an, ruft die Integration auch die verpassten Radaranalysen ab
(einen kleinen Teil jeder Datei) und speichert eine kleine Aufzeichnung des
jüngsten Regens auf der Festplatte. Ausschalten entfernt den Sensor und löscht
diese Aufzeichnung, sodass ein erneutes Einschalten sauber von vorn beginnt.

### Schwelle für Regenereignisse {#rain-event-threshold}

**Schwelle für Regenereignisse (mm pro Stunde)** legt fest, wie viel Regen ein
5-Minuten-Schritt braucht, um zu einem Ereignis des Sensors `Regenereignisse`
zu zählen. `0` bedeutet, dass jede Spur ein Ereignis bildet. Der Wert ist
unabhängig von der [Schwelle für Regenerkennung](#rain-detection-threshold),
daher können die Ereignisse und `Niederschlagsbeginn` voneinander abweichen,
wenn sich die beiden unterscheiden. Wird nur verwendet, wenn
*Regenereignisse verfolgen* an ist.

### Algorithmus für das Ende {#end-algorithm}

**Wann „Niederschlagsende“ den Regen als beendet ansieht** wählt zwischen:

- **Erste trockene Lücke** (Standard): das Ende des aktuellen Schauers. Es
  verschiebt sich bei Schauerwetter.
- **Niederschlag endet innerhalb von 2 h:** wenn innerhalb des
  Zwei-Stunden-Horizonts kein Regen mehr vorhergesagt ist. Stabiler, bleibt
  aber länger `unknown` („Unbekannt“).

Der DWD sagt nur zwei Stunden voraus, darüber hinaus ist der Sensor in beiden
Fällen `unknown`.

### Vergangene Stunde in der Reihe {#past-hour-in-the-series}

**Vergangene Stunde in die stündliche Vorhersagereihe aufnehmen** lässt das
Attribut `forecast_rolling_1h` von `Maximaler Stundenniederschlag nächste
120 min` eine Stunde früher beginnen. Die ersten Einträge enthalten dann
Regen, der schon gefallen ist, sodass ein Diagramm die vergangene Stunde und
die Vorhersage als eine Kurve zeigt. Der Wert des Sensors ändert sich nicht.

Die frühere Stunde wird aus den Radaranalysen der vergangenen Stunde gebildet,
ohne zusätzlichen Download. Nach einem Neustart oder nach einer
5-Minuten-Veröffentlichung, die der DWD nicht rechtzeitig bereitgestellt hat,
erscheint sie, sobald die Integration wieder eine volle Stunde an
Veröffentlichungen gesehen hat. Siehe
[RADVOR-RV-Nowcast](../entities/radvor-rv.md#peak-hourly-precipitation).

### Nicht verfügbar, wenn veraltet {#unavailable-when-out-of-date}

**Sensoren als nicht verfügbar anzeigen, wenn die Daten veraltet sind:** Wenn
der DWD nicht rechtzeitig eine neue Datei veröffentlicht, melden die
betroffenen Sensoren `unavailable` („Nicht verfügbar“), statt den letzten Wert
zu behalten. Schalte die Option aus, um immer den neuesten Messwert zu
behalten, auch wenn er dann Stunden alt sein kann. In beiden Fällen wird die
fehlende Datei im Hintergrund weiter abgerufen. Wie lange „rechtzeitig“ ist,
steht unter [Verfügbarkeit und Aktualität](../how-it-works/availability.md).
