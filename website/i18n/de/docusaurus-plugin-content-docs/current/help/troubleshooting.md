---
title: Fehlerbehebung
description: Was die Log-Meldungen von DWD Precipitation bedeuten und was zu tun ist, wenn Sensoren nicht verfügbar oder unbekannt sind.
---

Die meisten Meldungen dieser Integration beschreiben etwas, das der DWD getan
hat, und kein Problem mit deiner Einrichtung. Jede sagt, ob deine
Konfiguration betroffen ist (meist nicht) und dass weitere Versuche folgen.
Die Meldungen erscheinen im Log auf Englisch; sie sind hier im Wortlaut
zitiert.

## Ein Sensor ist kurz nicht verfügbar, oder eine Datei wurde nicht gefunden {#a-sensor-is-briefly-unavailable-or-a-file-was-not-found}

> DWD has not published the … release yet (HTTP 404). DWD OpenData is late;
> nothing is wrong with your setup. Retrying in …

Der DWD veröffentlicht oft ein paar Minuten zu spät. Die Integration
versucht es automatisch erneut, zuerst nach 60 Sekunden und dann in immer
längeren Abständen bis höchstens alle 5 Minuten (15 Minuten für
`Niederschlag gestern`). Ein Sensor wird erst `unavailable` („Nicht
verfügbar“), wenn seine nächste Datei mehr als 6 Minuten überfällig ist
(30 Minuten für `Niederschlag gestern`), und erholt sich beim nächsten
erfolgreichen Abruf.

Du musst nichts tun. Siehe
[Veröffentlichungszeitpunkte](../how-it-works/release-timing.md) und
[Verfügbarkeit und Aktualität](../how-it-works/availability.md).

## Sensoren bleiben nach der Einrichtung nicht verfügbar {#sensors-stay-unavailable-after-setup}

> Could not reach DWD OpenData for the … release (…). Check this machine's
> internet access.

Home Assistant erreicht `opendata.dwd.de` nicht. Prüfe die
Internetverbindung des Rechners, DNS und jede Firewall oder jeden Proxy
zwischen Home Assistant und dem Internet. Öffne
<https://opendata.dwd.de/weather/radar/composite/> in einem Browser im selben
Netzwerk, um zu sehen, ob der DWD erreichbar ist.

Wenn nur einige Sensoren nicht verfügbar sind, arbeiten die anderen
DWD-Produkte unabhängig weiter; das Log nennt das Produkt, das fehlschlägt.

## Ein Sensor zeigt Unbekannt: keine Radardaten für deinen Standort {#a-sensor-shows-unknown-no-radar-data-for-your-location}

> …: no radar data for your location in the … release (radar(s) missing from
> the DWD composite: depro). … this is a DWD outage, not a configuration
> problem.

Die Datei des DWD enthält keine Daten für deine Gitterzelle, meist weil ein
Radar aus dem Komposit des DWD ausgefallen ist; die Warnung nennt das oder
die fehlenden Radare (`depro` ist Prötzel bei Berlin), wenn sie es erkennen
kann. Der Sensor zeigt dann `unknown` („Unbekannt“). Die Sensoren erholen sich
von selbst, und das Log meldet, sobald wieder Daten da sind. Die Meldung
erscheint einmal pro Ausfall, nicht für jede Datei. Der DWD zeigt den
[aktuellen Status seiner Radarstandorte](https://www.dwd.de/DE/leistungen/radarniederschlag/rn_info/home_freie_radarstatus_kartendaten.html).

> …: no radar data for your location in the … release, the first one read.
> Either the location is outside the area this product covers, or a DWD radar
> is out.

Diese Meldung erscheint direkt nach der Einrichtung oder einem Neustart.
Kommen nie Daten an, liegt der Standort außerhalb des Gebiets, das dieses
Produkt abdeckt; siehe
[Gitterzellen-Suche](../how-it-works/grid-lookup.md#which-locations-are-covered).

Das gilt für jedes Produkt, auch für `Niederschlagsart aktuell` und die
RADOLAN-Sensoren. Die laufenden Summen überspringen die Zeitfenster ohne
Daten.

## Der Standort liegt nicht auf dem Gitter {#the-location-is-not-on-the-grid}

> The configured location is not on the grid of the … release (…): DWD's
> radar does not cover it.

Der Standort hat die grobe Prüfung bei der Einrichtung bestanden, liegt aber
außerhalb des Gebiets, das die Dateien des DWD abdecken. Lösche den Eintrag
und richte die Integration mit einem Standort in Deutschland neu ein.

## Eine Datei konnte nicht gelesen werden {#a-file-could-not-be-read}

> Could not read the … release (…). This is likely a change on DWD's side or
> a bug in the integration; please report it if it keeps happening.

Der DWD hat etwas geliefert, das diese Version nicht lesen kann. Wenn das
immer wieder passiert, [eröffne ein Issue](#reporting-a-problem).

## Teildownloads haben nicht funktioniert {#range-downloads-did-not-work}

> Reading whole DWD … archives: partial (range) downloads of … did not work.
> Values are not affected, but each update now downloads several times the
> data …

Normalerweise lädt die Integration nur die Teile der RADVOR-Archive herunter,
die sie braucht (Range-Anfragen, HTTP-Teildownloads). Etwas zwischen dir und
dem DWD (oder der DWD selbst) hat das nicht zugelassen, daher weicht sie auf
ganze Archive aus. Die Werte sind dieselben; nur die Datenmenge wächst. Ein
Proxy, der Anfragen umschreibt, kann die Ursache sein. Das Log meldet, wenn
Teildownloads wieder funktionieren.

## Alte Werte bleiben nach einem DWD-Ausfall stehen {#old-values-persist-after-a-dwd-outage}

Die erweiterte Option *Sensoren als nicht verfügbar anzeigen, wenn die Daten
veraltet sind* ist aus, daher wird der letzte Wert behalten. Schalte sie ein,
damit die Sensoren stattdessen `unavailable` melden. Siehe
[Verfügbarkeit und Aktualität](../how-it-works/availability.md#keeping-the-last-value-instead).

## Die Werte weichen von meinem Niederschlagsmesser ab {#the-values-differ-from-my-rain-gauge}

Das Radar schätzt den Regen in der Luft über einer 1-km-Zelle; ein
Niederschlagsmesser sammelt ihn an einem Punkt am Boden. Abweichungen von
einigen zehn Prozent bei einem einzelnen Schauer sind normal, und
Sommerschauer können einen Niederschlagsmesser wenige hundert Meter entfernt
verfehlen. Die angeeichten RADOLAN-Sensoren (`Niederschlag vorige Stunde`,
`Niederschlag gesamt`) kommen meist näher heran als die reinen Radarwerte.
Siehe [Die DWD-Produkte](../how-it-works/dwd-products.md).

## Debug-Protokollierung {#debug-logging}

So siehst du im Detail, was die Integration tut:

1. Gehe zu **Einstellungen > Geräte & Dienste > DWD Precipitation**.
2. Wähle im Menü **Debug-Protokollierung aktivieren**.
3. Warte, bis das Problem auftritt, und wähle dann **Debug-Protokollierung
   deaktivieren**. Home Assistant bietet die Logdatei zum Herunterladen an.

Oder in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.dwd_precipitation: debug
```

## Ein Problem melden {#reporting-a-problem}

[Eröffne ein Issue auf GitHub](https://github.com/Hoffmann77/ha-dwd-precipitation/issues)
mit:

- den Versionen der Integration und von Home Assistant,
- den Log-Meldungen, am besten mit Debug-Protokollierung,
- bei einem falschen Wert: dem Sensor, seinem Wert und der Uhrzeit sowie den
  Attributen, die mit *Metadaten als Sensorattribute anzeigen* erscheinen; sie
  sagen genau, aus welcher DWD-Datei der Wert stammt.

Deinen genauen Standort musst du nicht angeben; der nächste Ort genügt.
