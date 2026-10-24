# 0011 — Lücken in der Quelle des Trockenzählers werden gegen die Stunden von RW geprüft

Status: angenommen (2026.11.0)

## Kontext {#context}

`Timespan without precipitation` wird nur bei einem Messwert ab dem
Schwellwert zurückgesetzt; ein Messwert ohne Daten zählt daher als trocken. Am
13. Okt. 2026 fehlte das Radar Proetzel von 11:40 bis 17:40 UTC in der
RS-Analyse, und Berlin hatte während eines großen Regenereignisses sechs
Stunden lang keine RS-Daten (#109, #114). Regen in einer solchen Lücke setzte
die Trockenphase nie zurück. Regen, während HA *nicht lief*, wurde beim Start
schon über die aktuelle RW-Stunde und die 24 Stunden von SF erfasst, aber
nichts prüfte eine Lücke, während HA lief.

Das Archiv des DWD (CDC `RW-hdf5-261013`, `SF-hdf5-261013`) zeigt für diesen
Tag:

- RW und SF hatten während der ganzen Lücke Daten für Berlin Mitte, und jede
  Stunde lag bei 0,0 mm; dieser Ausfall verbarg dort also kein Zurücksetzen.
- Auch RADOLAN verlor Proetzel, aber nur in einigen Läufen: Die RW-Läufe zu
  :00 und :30 von 11:30 bis 16:30 haben ein Loch von 3731 Zellen bis etwa
  90 km um das Radar, das bis auf 28 km an Berlin Mitte heranreicht; einige
  Läufe zu :10 ein kleineres; die Läufe zu :20, :40 und :50 sowie SF sind
  vollständig. RW kann eine RS-Lücke daher dort füllen, wo seine eigenen Läufe
  die Zelle haben, und dort nicht, wo sie sie nicht haben.

## Entscheidung {#decision}

- Der Sensor hält `watched_until` fest, das Ende der neuesten Stunde, die die
  Quelle gemeldet hat. Beginnt die Stunde eines neuen Messwerts danach, blieb
  Zeit unbeobachtet: Die vollen RW-Stunden, die diese Strecke überlappen
  (`unwatched_hours`), werden im Hintergrund von OpenData abgerufen, und eine
  davon, die den Schwellwert erreicht, verschiebt `dry_since` auf ihr Ende.
  Eine Lücke, die kürzer ist als die Stunde der Quelle, braucht nichts, da der
  neue Messwert sie abdeckt.
- `watched_until` und die noch abzurufenden Stunden werden mit dem Anker
  gespeichert. Eine Zeit, in der Home Assistant nicht lief, ist daher eine
  Lücke wie jede andere, und ein Neustart setzt die Prüfung fort. Die
  Korrektur beim Start aus RW/SF bleibt, wie sie war.
- Nur RW, so weit zurück, wie OpenData es vorhält (die neueste Stunde und die
  47 davor, dasselbe Fenster wie beim Nachholen der RW-Summe). Neueste zuerst;
  eine Stunde verlässt die Liste, sobald sie abgerufen ist; der erste Fehler
  beendet die Runde, und nur ein neuer Messwert löst einen erneuten Versuch
  aus.

## Verworfene Alternativen {#alternatives-turned-down}

- **RW und SF nur bei Rückkehr der Quelle** (der Vorschlag im Issue: die
  Korrektur beim Start ausführen, wenn die Quelle zurückkommt). Die aktuelle
  RW-Stunde deckt nur die letzte Stunde einer längeren Lücke ab, und SF kann
  Regen nur auf einen Tag genau einordnen: Eine sechsstündige Lücke mit Regen
  darin würde `dry_since` auf etwa 24 Stunden zurück verschieben. Außerdem
  mischt es eine 24-Stunden-Summe hinein, die mit einem stündlichen
  Schwellwert verglichen wird.
- **Während der Lücke auf die Veröffentlichungen von RW hören.** Ebenfalls
  stundengenau, aber dafür müsste der Sensor einen zweiten Coordinator
  abonnieren, er verpasst die Stunden, die RW selbst nicht abrufen konnte, und
  hilft nicht bei einer Zeit, in der Home Assistant nicht lief. Die Stunden
  nachträglich abzurufen deckt alle drei Fälle mit dem Mechanismus ab, den die
  Summen schon nutzen.
- **Unbekannt als nass behandeln.** Jeder Ausfall würde eine lange
  Trockenphase zurücksetzen.
