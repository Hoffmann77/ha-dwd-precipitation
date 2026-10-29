# 0001 — Entitätsnamen nennen ihr Zeitfenster; eine ausgelieferte ID wird nie wiederverwendet

Status: angenommen (2026.11.0)

## Kontext {#context}

HA bildet eine Entitäts-ID aus dem Slug des englischen Namens, ein Name ist
also zugleich eine ID. Bis 2026.10.1 lauteten die Namen:

| Schlüssel | Name in 2026.10.1 | ID |
|-----------|-------------------|----|
| `radvor_rs_000` | Precipitation now | `precipitation_now` |
| `radvor_rs_060` | Precipitation next 1h | `precipitation_next_1h` |
| `radvor_rs_120` | Precipitation next 1–2h | `precipitation_next_1_2h` |
| `radvor_peak_1h_120` | Peak hourly precipitation next 2h | `peak_hourly_precipitation_next_2h` |
| `radvor_rv_max_intensity_060` | Peak intensity next 1h | `peak_intensity_next_1h` |
| `radvor_rv_max_intensity_120` | Peak intensity next 1–2h | `peak_intensity_next_1_2h` |
| `hymecng_precipitation_type` | Precipitation type | `precipitation_type` |
| `radolan_rw` | Precipitation last 1h | `precipitation_last_1h` |
| `radolan_rw_total` | Precipitation total (hourly) | `precipitation_total_hourly` |
| `radolan_sf_yesterday_total` | Precipitation total (daily) | `precipitation_total_daily` |

`tests/entity_ids.py` ist die vollständige Aufstellung nach Schlüssel,
einschließlich dessen, was seine ID behalten hat, und dessen, was seitdem neu
ist.

Drei Dinge waren an ihnen falsch:

- `Precipitation now` war RS `_000`, mm über die *vergangene Stunde*, benannt
  nach seiner Rolle; es klang wie eine Intensität.
- `next 1–2h` brauchte einen Hinweis, dass es die zweite Stunde ist, nicht die
  kommenden zwei.
- RS `_000` und RW deckten beide „die letzte Stunde“ unter Namen ab, die nichts
  miteinander zu tun hatten, und keiner von beiden sagte, welche Stunde.

## Entscheidung {#decision}

Ein Name nennt ein Zeitfenster nur, wenn das Fenster Teil des Werts ist, und
zwar in drei Formen: `last <N>` (ein gemessenes Fenster, das mit der neuesten
Veröffentlichung endet), `next <N>` (ein Vorhersagefenster) und die
Kalenderzeiträume `previous hour` / `yesterday`. Der RADVOR-Nowcast
(Kurzfristvorhersage) nennt Fenster in Minuten, passend zu seinen
5-Minuten-Schritten und den Attributen `minutes_until` (`next 60–120 min`);
RADOLAN bleibt bei Stunden und Tagen (`last 24h` behält seine ausgelieferte
Schreibweise, da ein Leerzeichen seinen Slug grundlos ändern würde). `now`
bedeutet die neueste 5-Minuten-Analyse. Alles andere trägt kein Fenster.

Damit ist RS `_000` `Precipitation last 60 min`, RW (eine volle Stunde, siehe
[0002](0002-rw-reads-the-clock-hour.md)) ist `Precipitation previous hour`, und
keine zwei Namen teilen sich ein Fenster, sodass keiner einen Hinweis auf die
Quelle braucht.

Die Schlüssel haben sich nicht geändert: Bestehende Installationen behalten
ihre IDs und sehen nur die neuen Namen; neue Installationen bekommen die neuen
IDs. Keine neue ID ist eine, die eine ausgelieferte Version einer anderen
Entität gegeben hat. So bedeutet eine ID auf jeder Installation dasselbe, und
„Entitäts-IDs neu erstellen“ in HA kann auf einer alten Installation nicht
kollidieren.

## Verworfene Alternativen {#alternatives-turned-down}

- **RS als `precipitation_last_1h`.** Auf einer alten Installation hält RW
  diese ID noch, das Neuerstellen der IDs würde RS also auf
  `precipitation_last_1h_2` legen.
- **Quellen-Zusätze**, `(radar)` / `(gauge-adjusted)`. Kurz auf dem
  Release-Branch nach 2026.10.0 vorhanden, nie ausgeliefert: Sobald keine zwei
  Namen ein Fenster teilen, ist die Quelle etwas, das die README erklärt, kein
  Name.
- **Schlüssel passend umbenennen.** Ein Schlüssel ist das Suffix der Unique ID;
  ihn zu ändern lässt die Entität des Nutzers samt ihrem Verlauf verwaist
  zurück.

## Folgen {#consequences}

Die README listet die alten IDs für Installationen von vor 2026.11.0; ein Test
prüft, dass sie jede umbenannte nennt (`tests/parser/test_docs.py`). Der
Setup-Test prüft die IDs einer neuen Installation und dass keine davon eine
alte ID eines anderen Schlüssels ist.
