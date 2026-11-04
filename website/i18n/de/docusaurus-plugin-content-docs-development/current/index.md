---
title: Entwicklung
description: Wie das Projekt DWD Precipitation aufgebaut ist und wo du anfängst, wenn du mitarbeiten willst.
---

DWD Precipitation ist eine benutzerdefinierte Integration für Home Assistant,
geschrieben in Python. Diese Seiten sind für alle, die sie verstehen oder
ändern wollen. Wenn du sie nur nutzen willst, fängst du am besten mit der
[Benutzerdokumentation](/) an.

## Das Repository {#the-repository}

| Pfad | Was er enthält |
|------|----------------|
| `custom_components/dwd_precipitation/` | Die Integration selbst |
| `custom_components/dwd_precipitation/radar/` | Der Kern ohne Home Assistant: Dateileser und reine Fachlogik |
| `tests/` | Fünf Teststufen, siehe [Tests und Prüfungen](tests-and-checks.md) |
| `scripts/` | Werkzeuge, um Fixtures zu erzeugen und die Veröffentlichungsverzögerungen des DWD zu prüfen |
| `docs/adr/` | Die [Architekturentscheidungen](/development/adr) (ADRs) |
| `website/` | Diese Dokumentationsseite, siehe [An dieser Dokumentation arbeiten](documentation.md) |
| `CLAUDE.md` | Der Leitfaden zur Codebasis: die Regeln, denen der Code folgt, direkt neben ihm abgelegt |

## Wo du weiterliest {#where-to-read-on}

- [Architektur](architecture.md): die Module, wie Daten vom DWD zu einer
  Entität fließen und wie Fehler behandelt werden.
- [Ein DWD-Produkt hinzufügen](adding-a-product.md): die Checkliste.
- [Tests und Prüfungen](tests-and-checks.md): was wo läuft und wie du es
  lokal ausführst.
- [Architekturentscheidungen](/development/adr): warum die Dinge so sind, wie
  sie sind, und wie sie vorher waren.

## Einrichten {#getting-set-up}

Das Projekt verwendet [uv](https://docs.astral.sh/uv/) für seine
Python-Umgebungen. Jede Teststufe hat ihre eigene Abhängigkeitsgruppe, sodass
eine schnelle Stufe kein installiertes Home Assistant braucht:

```sh
git clone https://github.com/Hoffmann77/ha-dwd-precipitation.git
cd ha-dwd-precipitation
uv run --group unit-test pytest tests/parser
```

Um eine Änderung in einem echten Home Assistant auszuprobieren, kopiere
`custom_components/dwd_precipitation` in den Ordner `custom_components` einer
Entwicklungsinstanz (oder lege einen symbolischen Link an) und starte sie neu.

## Mitwirken {#contributing}

- Fehler und Ideen gehören in die
  [GitHub-Issues](https://github.com/Hoffmann77/ha-dwd-precipitation/issues).
- Pull Requests sind willkommen. Halte eine Änderung fokussiert, füge Tests
  in der passenden Stufe hinzu und aktualisiere die Dokumentation, die sie
  betrifft, auf Englisch und Deutsch.
- Eine Entscheidung, die das Verhalten der Integration ändert oder eine
  frühere umstößt, bekommt ein ADR.
- Nur Abhängigkeiten mit Binary Wheels, die sich sauber in Home Assistant
  installieren lassen, sind zulässig. Heute sind das `numpy` und `h5py`;
  schwere Pakete wie wradlib, pyproj oder GDAL sind es nicht.
