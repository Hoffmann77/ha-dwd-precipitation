---
title: An dieser Dokumentation arbeiten
description: Wie du die Dokumentationswebsite von DWD Precipitation startest, schreibst und übersetzt.
---

Diese Website wird mit [Docusaurus](https://docusaurus.io/) aus dem Ordner
`website/` des Repositorys gebaut und auf GitHub Pages veröffentlicht, wenn
ein Release veröffentlicht wird.

## Lokal starten {#running-it-locally}

Du brauchst Node.js (die Version in `website/.nvmrc`) und npm.

```sh
cd website
npm ci
npm start              # Englisch, lädt bei jeder Änderung neu
npm run start:de       # Deutsch
```

Die Suche funktioniert nur in einem Produktions-Build:

```sh
npm run build          # beide Sprachen; schlägt bei kaputten Links fehl
npm run serve
```

## Wo die Seiten liegen {#where-the-pages-live}

Die Website hat drei Teile, jeder mit eigenem Ordner und eigener Seitenleiste:

| Teil | Englische Quellen | Seitenleiste | URL |
|------|-------------------|--------------|-----|
| Benutzerdokumentation | `website/docs/` | `website/sidebars.js` | `/` |
| Entwicklung | `website/development/` | `website/sidebarsDevelopment.js` | `/development` |
| Architekturentscheidungen | `docs/adr/` | `website/sidebarsAdr.js` | `/development/adr` |

Die ADRs werden direkt aus `docs/adr/` gelesen, damit sie neben dem Code
bleiben. Ein neues ADR kommt über seinen Dateinamen in die Seitenleiste;
eine Änderung an der Seitenleiste ist nicht nötig.

`.md`-Dateien sind CommonMark, `.mdx`-Dateien MDX. Nimm `.md`, außer eine
Seite braucht React-Komponenten. Admonitions (`:::note`, `:::warning`)
funktionieren in beiden.

### Links {#links}

- Innerhalb eines Teils verlinkst du auf die Datei:
  `[Configuration](../getting-started/configuration.md)`. Der Build prüft
  diese Links.
- Über Teile hinweg verlinkst du auf den URL-Pfad:
  `[ADR 0007](/development/adr/0007-staleness-deadline-on-the-overdue-release)`.
  Er führt in dieselbe Sprache, in der der Leser gerade ist.
- Bilder aus `docs/assets/` werden im Wurzelverzeichnis der Website
  ausgeliefert: `![Setup dialog](/screenshot_config_flow.png)`.

## Englisch und Deutsch {#english-and-german}

Jede Seite existiert auf Englisch und Deutsch. Die deutschen Seiten bilden
die englischen Ordner Datei für Datei ab:

| Englisch | Deutsch |
|----------|---------|
| `website/docs/` | `website/i18n/de/docusaurus-plugin-content-docs/current/` |
| `website/development/` | `website/i18n/de/docusaurus-plugin-content-docs-development/current/` |
| `docs/adr/` | `website/i18n/de/docusaurus-plugin-content-docs-adr/current/` |

Eine Änderung an einer Seite oder ein neues ADR kommt also mit seinem
deutschen Gegenstück. `tests/parser/test_website.py` schlägt fehl, wenn eine
Seite in einer der beiden Sprachen fehlt.

Beschriftungen außerhalb der Seiten (Navigationsleiste, Fußzeile,
Kategorien der Seitenleiste) werden in den JSON-Dateien unter
`website/i18n/de/` übersetzt. Nachdem du eine Kategorie der Seitenleiste oder
einen Eintrag der Navigationsleiste hinzugefügt hast, führe
`npm run write-translations` aus, um seinen Schlüssel anzulegen, und übersetze
ihn dann. `code.json` enthält nur die Theme-Texte, die Docusaurus nicht schon
selbst übersetzt.

Die deutschen Seiten verwenden die deutschen Entitätsnamen aus
`custom_components/dwd_precipitation/translations/de.json`, da Home Assistant
sie auf Deutsch so anzeigt. Die Entitäts-IDs sind in beiden Sprachen gleich:
Home Assistant bildet sie aus dem englischen Namen. Die Seiten sprechen
die Lesenden mit „du“ an, wie die deutsche Oberfläche von Home Assistant.

Deutsche Überschriften tragen die ID der englischen Überschrift, die sie
übersetzen, damit Links auf einen Anker in beiden Sprachen funktionieren:

```md
## Quelle des Trockenzählers {#dry-streak-source}
```

Die ID ist der Slug, den Docusaurus aus der englischen Überschrift bildet.
Fehlt sie oder stimmt sie nicht, schlägt der Build fehl, sobald ein Link auf
die Überschrift zeigt; `tests/parser/test_website.py` prüft alle
Überschriften.

## Veröffentlichen {#publishing}

`docs-deploy.yml` baut und veröffentlicht die Website, wenn ein Release
veröffentlicht wird, sodass die Dokumentation das neueste Release beschreibt.
Um eine reine Dokumentationskorrektur zwischendurch zu veröffentlichen,
starte den Workflow von Hand im Reiter „Actions“. `docs-build.yml` baut jeden
Pull Request, der die Dokumentation berührt, sodass ein kaputter Link
auffällt, bevor er gemergt wird.
