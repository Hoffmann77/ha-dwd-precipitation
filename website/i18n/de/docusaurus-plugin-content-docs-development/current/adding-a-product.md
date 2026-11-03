---
title: Ein DWD-Produkt hinzufügen
description: Die Checkliste, um der Integration ein weiteres Radarprodukt des DWD hinzuzufügen.
---

Jedes DWD-Produkt ist eine Coordinator-Unterklasse in `products.py`. Ein
neues hinzuzufügen berührt eine Handvoll Stellen, in dieser Reihenfolge.

## Checkliste {#checklist}

1. **Leite von einer Basisklasse ab** in `products.py`:
   - `WholeFileProduct` für eine Datei pro Veröffentlichung, die ganz
     dekodiert wird (HymecNG, RADOLAN);
   - `RadvorProduct` für ein RADVOR-Tar-Archiv (RS, RV);
   - `BaseProductUpdateCoordinator` selbst nur, wenn keine der beiden passt.
2. **Setze die Klassenkonstanten:** `PRODUCT_KEY`, `PRODUCT_LABEL`,
   `RELEASE_INTERVAL`, `RELEASE_DELAY`, `RELEASE_OFFSET` und `OVERDUE_GRACE`
   (ausgeschrieben, auch wenn es `DEFAULT_OVERDUE_GRACE` ist; ein Test
   erzwingt das), `COVERAGE_KEYS` (die Unterschlüssel, die ohne Daten für die
   Zelle `None` sind; ein Test prüft, dass jedes Produkt sie hat), und
   `MAX_FAST_POLL_INTERVAL`, wenn der Standardwert nicht passt. Siehe
   [unten](#picking-the-release-constants).
3. **Füge das URL-Muster** in `radar/urls.py` hinzu; `_get_url` leitet die URL
   aus `PRODUCT_KEY` ab.
   - Ein `WholeFileProduct` implementiert das blockierende
     `_parse(content, ts)`; die Basis lädt die Datei herunter und führt es im
     Executor aus.
   - Ein `RadvorProduct` implementiert `_fetch_and_parse`.
   - Halte `_fetch_and_parse` frei von Seiteneffekten; alles andere gehört in
     `_async_on_new_release`.
4. **Das Gitter** kommt aus der Gruppe `/where` jeder Datei
   (`radar/grid.py`), sodass ein Produkt auf einem anderen
   polarstereografischen Gitter nichts weiter braucht; eines in einer anderen
   Projektion braucht diese Projektion in `grid.py`.
5. **Füge Sensorbeschreibungen** in `sensor.py` hinzu (ein neues
   `*_SENSORS`-Tupel).
6. **Registriere die Klasse** im Tupel `PRODUCT_CLASSES` von `__init__.py`.
7. **Registriere die Sensoren** in `async_setup_entry` von `sensor.py`, und
   trage den Namen jedes `translation_key` in `translations/en.json` und
   `translations/de.json` ein. Die beiden Dateien müssen identische Schlüssel
   behalten; ein Test prüft das.
8. **Füge es zu `PRODUCTS`** in `scripts/check_release_delay.py` hinzu, damit
   sein `RELEASE_DELAY` mit dem abgeglichen wird, was der DWD tatsächlich
   tut.
9. **Dokumentiere es**: eine Entitätsseite in `website/docs/entities/` und
   ihre deutsche Übersetzung, dazu die Tabellen in der Einführung, der
   Entitätsübersicht und
   [Veröffentlichungszeitpunkte](/how-it-works/release-timing).

## Die Veröffentlichungskonstanten wählen {#picking-the-release-constants}

- **`RELEASE_INTERVAL` und `RELEASE_OFFSET`** beschreiben die Termine: Alle
  5 Minuten um :00, :05, … ist ein Intervall von 5 Minuten ohne Versatz;
  stündlich um :50 ist ein Intervall von 1 Stunde mit einem Versatz von
  50 Minuten.
- **`RELEASE_DELAY`** gibt an, wie lange nach ihrem Termin eine Datei auf
  Open Data ist. Miss ihn an den `Last-Modified`-Headern aktueller Dateien
  (das tut `scripts/check_release_delay.py`) und nimm einen Wert auf oder über
  dem Mittelwert: Ein Abruf, bevor der DWD veröffentlicht, kostet jedes Mal
  eine fehlgeschlagene Anfrage und einen erneuten Versuch.
- **`OVERDUE_GRACE`** gibt an, wie lange der DWD Zeit bekommt, eine
  überfällige Veröffentlichung nachzuliefern, bevor die Sensoren veralten.
  Sie darf kein ganzzahliges Vielfaches von `RELEASE_INTERVAL` sein, sonst
  fällt die Frist mit einem Abruf zusammen; ein Test erzwingt das für jedes
  Produkt.
- **`USE_LOCAL_TIME`** ist für ein Produkt, dessen Termine in Ortszeit
  liegen, wie das tägliche `sf_2350`.

## Die Entitäten benennen {#naming-the-entities}

Folge den Benennungsregeln in `CLAUDE.md` und
[ADR 0001](/development/adr/0001-entity-names-state-their-window): ein
Zeitfenster im Namen nur, wenn es Teil des Werts ist, `last` / `next` /
Kalenderzeiträume, Einheiten, die dem Produkt folgen. Gib einer neuen Entität
nie eine ID, die eine veröffentlichte Version einer anderen gegeben hat;
`tests/entity_ids.py` verzeichnet sie.
