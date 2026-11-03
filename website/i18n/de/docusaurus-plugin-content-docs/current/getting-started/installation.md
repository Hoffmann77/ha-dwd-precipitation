---
title: Installation
description: DWD Precipitation aus dem Marketplace, mit HACS oder von Hand installieren und dann zu Home Assistant hinzufügen.
---

## Voraussetzungen {#requirements}

- Home Assistant 2025.4 oder neuer, das `opendata.dwd.de` über HTTPS
  erreicht.
- Ein Standort in Deutschland oder nahe seiner Grenze. Was abgedeckt ist,
  steht unter [Gitterzellen-Suche](../how-it-works/grid-lookup.md).

Ein Konto oder API-Schlüssel ist nicht nötig.

Wie du installierst, hängt von deiner Version von Home Assistant ab: Ab Home
Assistant 2026.11 kommen Community-Integrationen aus dem **Marketplace**, der
eingebaut ist. Davor kamen sie aus [HACS](https://hacs.xyz), das du selbst
installiert hast.

## Installation aus dem Marketplace (Home Assistant 2026.11 und neuer) {#install-from-the-marketplace}

1. Öffne DWD Precipitation mit diesem Button im Marketplace:

   [![Öffne deine Home-Assistant-Instanz und öffne ein Repository im Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=integration)

   Oder öffne den Marketplace in den **Einstellungen** und suche nach
   **DWD Precipitation**. Beim ersten Öffnen bittet dich der Marketplace, einen
   Hinweis zu bestätigen: Inhalte der Community werden nicht vom
   Home-Assistant-Projekt geprüft.
2. Wähle **Installieren**, prüfe die Version und bestätige.
3. Die Einrichtung öffnet sich von selbst, sobald die Installation fertig
   ist. Ein Neustart ist nicht nötig. Hast du sie geschlossen,
   [füge die Integration](#add-the-integration) selbst hinzu.

**Updates** erscheinen in den **Einstellungen** bei den Updates von Home
Assistant selbst, mit den Versionshinweisen. Starte Home Assistant nach einem
Update neu; eine Reparatur unter **Einstellungen > System > Reparaturen**
erinnert dich daran und kann den Neustart für dich auslösen. Eine neue
Version kann ein paar Stunden brauchen, bis sie dort erscheint, weil der
Marketplace den Katalog nur alle paar Stunden nach neuen Versionen fragt.

### Von HACS kommend {#coming-from-hacs}

Hast du DWD Precipitation mit HACS installiert, musst du nichts tun: Wenn
Home Assistant 2026.11 zum ersten Mal startet, übernimmt der Marketplace
alles, was HACS installiert hat. DWD Precipitation bleibt installiert, behält
seine Einstellungen und Entitäten und bekommt weiter Updates.

## Installation mit HACS (Home Assistant 2026.10 und älter) {#install-with-hacs-recommended}

Wenn du [HACS](https://hacs.xyz) noch nicht hast, installiere es zuerst.

1. Öffne DWD Precipitation mit diesem Button in HACS:

   [![Öffne deine Home-Assistant-Instanz und öffne ein Repository im Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=integration)

   Oder öffne HACS und suche nach **DWD Precipitation**.
2. Wähle **Herunterladen**.
3. [Starte Home Assistant neu](#restart-home-assistant).
4. [Füge die Integration hinzu](#add-the-integration).

HACS zeigt eine Benachrichtigung, wenn eine neue Version erschienen ist;
aktualisiere von dort und starte Home Assistant danach erneut neu.

## Manuelle Installation {#manual-installation}

1. Lade die neueste Version von
   [GitHub Releases](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
   herunter und entpacke sie.
2. Kopiere den Ordner `custom_components/dwd_precipitation` in den Ordner
   `custom_components` deines Home-Assistant-Konfigurationsverzeichnisses,
   sodass am Ende `/config/custom_components/dwd_precipitation/` existiert.
3. [Starte Home Assistant neu](#restart-home-assistant).
4. [Füge die Integration hinzu](#add-the-integration).

Zum Aktualisieren ersetzt du diesen Ordner durch den aus der neuen Version.
Eine manuelle Installation wird nicht automatisch aktualisiert.

## Home Assistant neu starten {#restart-home-assistant}

Nach der Installation mit HACS oder von Hand und nach jedem Update braucht
Home Assistant einen Neustart, um den neuen Code zu laden
(**Einstellungen > System > Neu starten**). Nur eine erste Installation aus
dem Marketplace kommt ohne aus.

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
2. Entferne auch den Code:
   - **Marketplace:** Löschst du den letzten Eintrag, fragt Home Assistant,
     ob es DWD Precipitation auch deinstallieren soll. Du kannst es auch
     später auf seiner Seite im Marketplace deinstallieren (Menü mit den drei
     Punkten). Solange noch ein Eintrag existiert, deinstalliert der
     Marketplace es nicht, sondern bietet an, den Eintrag zu löschen und
     dann zu deinstallieren. Hat Home Assistant die Integration noch geladen,
     bittet dich eine Reparatur um einen Neustart.
   - **HACS:** Entferne es in HACS und starte Home Assistant neu.
   - **Manuelle Installation:** Lösche den Ordner
     `custom_components/dwd_precipitation` und starte Home Assistant neu.
