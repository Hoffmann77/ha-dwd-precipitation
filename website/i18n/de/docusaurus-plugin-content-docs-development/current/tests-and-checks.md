---
title: Tests und Prüfungen
description: Die Teststufen von DWD Precipitation, die CI-Workflows und wie du sie lokal ausführst.
---

## Die Teststufen {#the-test-tiers}

Die Tests sind in fünf Stufen aufgeteilt, ein Verzeichnis pro
Abhängigkeitsgruppe. Jede Stufe entspricht einem CI-Job, und die Jobs wählen
Tests nach Verzeichnis aus, sodass eine neue Testdatei ohne jede Änderung an
der CI mitläuft.

| Verzeichnis | Braucht Home Assistant | Braucht Netzwerk | Abhängigkeitsgruppe | Blockiert PRs |
|-------------|------------------------|------------------|---------------------|---------------|
| `tests/parser/` | nein | nein | `unit-test` | ja |
| `tests/integration/` | ja | nein | `ha-test` | ja |
| `tests/reference/` | nein | nein | `wradlib-comparison` | ja |
| `tests/live/` | nein | ja | `unit-test` | nein, zeitgesteuert |
| `tests/live_wradlib/` | nein | ja | `wradlib-comparison` | nein, zeitgesteuert |

Der Grundsatz: Tests, die Pull Requests blockieren, sind deterministisch.
Alles, was von der Außenwelt abhängt (DWD Open Data, ein neueres Home
Assistant), läuft zeitgesteuert und eröffnet bei einem Fehlschlag ein
Tracking-Issue, statt Merges zu blockieren.

- **parser**: der Code ohne Home Assistant, dazu Prüfungen über das ganze
  Repository: Die englischen und deutschen Übersetzungen definieren dieselben
  Schlüssel, die Upgrade-Seite nennt die alte ID jeder umbenannten Entität,
  und jede Seite dieser Website existiert in beiden Sprachen.
- **integration**: die Home-Assistant-Schicht, auf einer echten
  `hass`-Instanz.
- **reference**: die Parser und die Gitterzellen-Suche im Vergleich mit
  [wradlib](https://github.com/wradlib/wradlib), auf eingecheckten echten
  DWD-Dateien.
- **live**: lädt die echten Dateien von heute herunter und parst sie,
  einschließlich der Range-Anfragen, und prüft, dass RS weiterhin der Summe
  der Schritte von RV entspricht.
- **live_wradlib**: der wradlib-Vergleich auf den Dateien von heute für jedes
  Produkt. Hier würde sich eine Änderung des DWD-Gitters zeigen, da die
  Integration selbst ihr folgt.

## Lokal ausführen {#running-them-locally}

```sh
# Schnell, deterministisch, ohne Home Assistant
uv run --group unit-test pytest tests/parser
uv run --group wradlib-comparison pytest tests/reference

# Home-Assistant-Laufzeit (nur Linux)
uv run --group ha-test pytest tests/integration

# Live-Prüfungen gegen DWD Open Data
uv run --group unit-test pytest tests/live -m live
uv run --group wradlib-comparison pytest tests/live_wradlib -m live
```

`tests/README.md` beschreibt die Fixtures und Factories und wie die Fixtures
aus echten Dateien neu erzeugt werden.

## Lint- und Typprüfungen {#lint-and-type-checks}

- **ruff** (nur F-Regeln) auf dem Repository:
  `uv run --only-group lint ruff check .`
- **pyright** (Basic-Modus) auf der Komponente, gegen die eigenen Typen von
  Home Assistant: `uv sync --only-group typecheck && uv run --no-sync pyright`.
  Halte es bei 0 Fehlern: Behebe einen Befund, oder ignoriere ihn in seiner
  Zeile mit Begründung.

## CI-Workflows {#ci-workflows}

| Workflow | Wann | Was |
|----------|------|-----|
| `tests.yml` | PRs, Pushes auf main | Stufen parser, integration und reference, ruff, pyright |
| `docs-build.yml` | PRs, die die Dokumentation berühren | baut diese Website in beiden Sprachen; schlägt bei kaputten Links fehl |
| `docs-deploy.yml` | ein Release wird veröffentlicht | veröffentlicht diese Website auf GitHub Pages |
| `live.yml` | täglich | Live-Download und -Parsen; eröffnet bei Fehlschlag ein Issue |
| `live-wradlib.yml` | täglich oder von Hand | wradlib-Vergleich auf Live-Dateien; eröffnet bei Fehlschlag ein Issue |
| `ha-compat.yml` | wöchentlich | die Stufe integration gegen das neueste und das Dev-Test-Harness von Home Assistant |
| `hassfest.yaml`, `validate.yaml` | Pushes, PRs, täglich | Validierung des Home-Assistant-Manifests und für HACS |
| `release-delay.yml` | zeitgesteuert | prüft das `RELEASE_DELAY` jedes Produkts gegen die tatsächliche Veröffentlichung des DWD |
| `release-drafter.yml` | Pushes auf main, PRs | entwirft die nächsten Release Notes |

### Live-wradlib-Vergleich für deine eigenen Orte {#live-wradlib-comparison-for-your-own-places}

`live-wradlib.yml` lässt sich im Reiter „Actions“ von Hand starten
(**Live wradlib comparison > Run workflow**), um deine eigenen Orte gegen die
neuesten Dateien zu prüfen, zum Beispiel dort, wo das Radar gerade Regen
zeigt. Die Eingabe `locations` nimmt `name=lat,lon` oder `lat,lon`, getrennt
durch `;`. Die Job-Zusammenfassung bekommt eine Tabelle mit dem Wert jedes
Produkts pro Ort. Lokal ist dieselbe Eingabe die Umgebungsvariable
`DWD_LOCATIONS`.

### Prüfung der Veröffentlichungsverzögerung {#release-delay-check}

`scripts/check_release_delay.py` mittelt die beobachtete Verzögerung
aktueller Dateien (ihr `Last-Modified`-Header minus der Termin im Namen) und
markiert ein Produkt, dessen Mittelwert sein konfiguriertes `RELEASE_DELAY`
übersteigt. Der Workflow eröffnet oder aktualisiert ein Tracking-Issue nur,
wenn ein Produkt bei zwei aufeinanderfolgenden Läufen markiert wird, sodass
einmaliges Rauschen niemanden alarmiert.
