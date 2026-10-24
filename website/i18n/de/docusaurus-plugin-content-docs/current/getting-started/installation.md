---
title: Installation
description: DWD Precipitation mit HACS oder von Hand installieren und dann zu Home Assistant hinzufügen.
---

## Voraussetzungen {#requirements}

- Home Assistant 2025.4 oder neuer, das `opendata.dwd.de` über HTTPS
  erreicht.
- Ein Standort in Deutschland oder nahe seiner Grenze. Was abgedeckt ist,
  steht unter [Gitterzellen-Suche](../how-it-works/grid-lookup.md).

Ein Konto oder API-Schlüssel ist nicht nötig.

## Installation mit HACS (empfohlen) {#install-with-hacs-recommended}

Wenn du [HACS](https://hacs.xyz) noch nicht hast, installiere es zuerst.

1. Füge dieses Repository mit diesem Button zu HACS hinzu:

   [![Öffne deine Home-Assistant-Instanz und öffne ein Repository im Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=Integration)

2. Wähle in HACS **Herunterladen**.
3. [Starte Home Assistant neu](#restart-home-assistant).
4. [Füge die Integration hinzu](#add-the-integration).

HACS zeigt eine Benachrichtigung, wenn eine neue Version erschienen ist;
aktualisiere von dort und starte Home Assistant danach erneut neu.

### Das Repository von Hand hinzufügen {#adding-the-repository-by-hand}

Wenn der Button bei dir nicht funktioniert, füge das Repository selbst zu
HACS hinzu:

1. Öffne HACS.
2. Wähle die drei Punkte oben rechts, dann **Benutzerdefinierte Repositories**.
3. Gib `https://github.com/Hoffmann77/ha-dwd-precipitation` als Repository ein
   und wähle **Integration** als Typ.
4. Wähle **Hinzufügen**. DWD Precipitation erscheint jetzt in HACS und kann
   heruntergeladen werden.

## Manuelle Installation {#manual-installation}

1. Lade die neueste Version von
   [GitHub Releases](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
   herunter und entpacke sie.
2. Kopiere den Ordner `custom_components/dwd_precipitation` in den Ordner
   `custom_components` deines Home-Assistant-Konfigurationsverzeichnisses,
   sodass am Ende `/config/custom_components/dwd_precipitation/` existiert.

Zum Aktualisieren ersetzt du diesen Ordner durch den aus der neuen Version.
Eine manuelle Installation wird nicht automatisch aktualisiert.

## Home Assistant neu starten {#restart-home-assistant}

Home Assistant lädt eine neue oder aktualisierte benutzerdefinierte
Integration nur beim Start. Starte es daher nach dem Installieren oder
Aktualisieren neu (**Einstellungen > System > Neu starten**).

## Die Integration hinzufügen {#add-the-integration}

Nutze diesen Button:

[![Öffne deine Home-Assistant-Instanz und beginne mit der Einrichtung einer neuen Integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dwd_precipitation)

Oder füge sie selbst hinzu:

1. Gehe zu **Einstellungen > Geräte & Dienste**.
2. Wähle **Integration hinzufügen** und suche nach **DWD Precipitation**.
3. Gib einen Namen ein und wähle den Standort. Zu beidem siehe
   [Konfiguration](configuration.md).

Die Sensoren füllen sich innerhalb weniger Minuten: Jedes DWD-Produkt wird
beim Start einmal abgerufen und danach immer dann, wenn der DWD eine neue
Datei veröffentlicht.

## Die Integration entfernen {#removing-the-integration}

1. Gehe zu **Einstellungen > Geräte & Dienste > DWD Precipitation**, öffne das
   Menü des Eintrags und wähle **Löschen**. Damit werden auch die gespeicherten
   Daten der Integration gelöscht, etwa die Aufzeichnung der Regenereignisse.
2. Um auch den Code zu entfernen, entferne ihn in HACS (oder lösche den Ordner
   `custom_components/dwd_precipitation`) und starte Home Assistant neu.
