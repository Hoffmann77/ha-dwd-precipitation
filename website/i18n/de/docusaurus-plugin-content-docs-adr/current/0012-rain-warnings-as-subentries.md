# 0012 — Regenwarnungen sind Untereinträge, die die Sicht der Regenereignisse filtern

Status: angenommen (2026.11.0)

## Kontext {#context}

Der Sensor `Regenereignisse` (ADR 0006) verfolgt jeden Regenschauer von der
Vorhersage bis zur Messung und überließ Warnstufen den Blueprints. Die meisten
wollen aber nur die Warnung: „Sag mir 60 Minuten, bevor es auf die Wäsche
regnet.“ Das aus der Sicht zu bauen, braucht einen Blueprint oder ein
Template, das Zeitstempel und Mengen vergleicht und mit einer Vorhersage
zurechtkommt, die sich alle 5 Minuten ändert.

Home Assistant 2025.3 hat Konfigurations-Untereinträge eingeführt: vom Nutzer
angelegte Einträge unter einem Eintrag, jeder mit eigenem Ablauf, eigenen
Entitäten und Geräten.

## Entscheidung {#decision}

- **Eine Regenwarnung ist ein Untereintrag** eines Standorts
  (`rain_warning`), mit einem Namen (ihrem Titel), einer Vorlaufzeit (5 bis
  120 min in 5er-Schritten) und optionalen Mindestwerten für die Summe des
  Ereignisses, seine nasseste Stunde und seine nassesten 10 Minuten,
  verknüpft mit „einer“ oder „alle“. Geändert wird sie mit dem Schritt
  `reconfigure` des Untereintrags, nicht mit einer Zahlen-Entität. Ihre Daten
  liest `rain_warning_rule()` gegen eine Tabelle von Standardwerten, wie
  `DwdOptions`.
- **Keine eigene Ereignislogik.** Eine Warnung ist ein Filter über die Sicht
  der Regenereignisse (`radar/rain_warning.py`): `rain`, solange ein laufendes
  Ereignis den Filter besteht, `soon`, solange ein bevorstehendes, das ihn
  besteht, innerhalb der Vorlaufzeit beginnt, sonst `dry`. Verglichen wird der
  Block `total` des Ereignisses. Ohne Sicht ist der Zustand unbekannt, nicht
  trocken.
- **Die Ereignisverfolgung läuft, wenn sie gebraucht wird.** Sie läuft für
  die Option `rain_events` oder für eine beliebige Regenwarnung
  (`tracks_rain_events`); die Option steuert nur noch die Entität
  `Regenereignisse`. Der Speicher wird gelöscht, sobald keines von beiden ihn
  nutzt. Das ersetzt den Teil „die Option steuert alles“ von ADR 0006: Die
  Warnungen sollen nicht von einer Option abhängen, deren erklärter Zweck
  Blueprints sind, und die Verfolgung kostet im normalen Betrieb keinen
  zusätzlichen Download (die Analyse kommt mit der RV-Datei, die ohnehin
  dekodiert wird; Nachholabrufe folgen nur einer verpassten Veröffentlichung).
- **Beurteilt pro Veröffentlichung, nicht pro Minute.** Eine Warnung wird
  beurteilt, wenn RV eine neue Sicht bringt, mit der Vorlaufzeit gemessen ab
  der Ankunft dieser Veröffentlichung. Sie kann bis zu eine Veröffentlichung
  (5 min) später angehen, was innerhalb der 3 bis 10 Minuten liegt, die die
  Veröffentlichung beim DWD ohnehin kostet. Eine Prüfung jede Minute würde für
  einen Countdown in einem Attribut jede Minute eine Zustandszeile schreiben;
  das Attribut `start` ist stattdessen ein Zeitstempel, den das Frontend
  relativ anzeigt.
- **Zwei Erinnerungen, im Arbeitsspeicher.** Ein Ereignis, das den Filter
  einmal bestanden hat, besteht ihn, bis es endet (und das Ereignis, das es
  bei einer Verschmelzung aufnimmt, erbt das), damit ein laufender Schauer,
  dessen Vorhersage schrumpft, die Warnung nicht ausschaltet. Ein Ereignis,
  das `soon` war, bleibt für die eine Veröffentlichung `soon`, in der die
  Vorhersage es verliert (`unseen`). Beides hält pro Warnung ein
  `RainWarning`, das ihre zwei Entitäten teilen und das jede Sicht einmal
  beurteilt; nach einem Neustart werden die Ereignisse neu beurteilt.
- **Zwei Entitäten auf einem eigenen Gerät.** Ein binärer Sensor
  („Regenwarnung“, an bei `rain` oder `soon`) und ein Enum-Sensor
  („Regenwarnung Status“, mit `event_id`, `start`, `mm`, `peak_1h`,
  `peak_10min` des Ereignisses und einem reservierten `type`, alle nicht
  aufgezeichnet). Home Assistant hält ein Gerät in einem Untereintrag: Fügt
  man die Entitäten eines Untereintrags dem Gerät des Standorts hinzu, wandert
  dieses Gerät in den Untereintrag, was 2026.x meldet und 2027.8 verweigert.
  Daher ist jede Warnung ein Gerät, benannt nach dem Standort und der Warnung
  („Home Wäsche“), und die Entitäts-IDs sind
  `binary_sensor.<standort>_<warnung>_rain_warning` und
  `sensor.<standort>_<warnung>_rain_warning_status`, unabhängig von der
  Sprache der Oberfläche. Die Unique IDs sind
  `<entry_id>_<subentry_id>_rain_warning` und `..._rain_warning_status`.
- **Namen sind pro Standort eindeutig**, als Slug verglichen, damit zwei
  Warnungen nie um eine Entitäts-ID streiten.
- **Home Assistant 2025.4 oder neuer** (`hacs.json`): Die Hilfsfunktionen
  des Untereintrags-Ablaufs, die sie nutzt (`_get_entry`,
  `_get_reconfigure_subentry`), haben ihre endgültigen Namen ab 2025.4.

## Verworfene Alternativen {#alternatives-turned-down}

- **Die Warnungen auf dem Gerät des Standorts.** Home Assistant verweigert das
  ab 2027.8 (siehe oben).
- **Ein Takt jede Minute mit einem Countdown `starts_in_min`.** Etwa 1.440
  Zustandszeilen am Tag pro Warnung, trockene Tage eingeschlossen, für einen
  Wert, den das Frontend aus `start` ableiten kann.
- **Eine Niederschlagsart aus benachbarten Zellen von HymecNG.** Eine
  Schätzung; das Attribut `type` bleibt `null`, bis die Sicht der
  Regenereignisse eine gemessene Art enthält.
- **Die Option `rain_events` voraussetzen.** Man müsste einen
  Blueprint-Sensor einschalten, den man nicht will, und es bliebe offen, was
  mit den Warnungen geschieht, wenn man ihn ausschaltet.
- **Eigene Ereignislogik pro Warnung.** Sie würde Zuordnung, Verschmelzung und
  Nachholen der Verfolgung verdoppeln und könnte `Regenereignisse`
  widersprechen.
