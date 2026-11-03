# 0003 — Die 10-Minuten-Läufe von RW speisen den Trockenzähler, sonst nichts

Status: angenommen (2026.11.0)

## Kontext {#context}

Die Läufe von RW innerhalb der Stunde (siehe
[0002](0002-rw-reads-the-clock-hour.md)) sind genauso stark mit Bodenmessungen
angeeicht wie der stündliche, und alle 10 Minuten erscheint ein neuer.
`Timespan without precipitation` wird zurückgesetzt, wenn eine Summe über die
vergangene Stunde einen Schwellwert erreicht; nach dem stündlichen Lauf von RW
gezählt, kann das Zurücksetzen bis zu einer Stunde zu spät erscheinen.

## Entscheidung {#decision}

- `RadolanRW10` (`rw_10min`) liest jeden Lauf, und der Trockenzähler zählt ihn,
  wenn seine Quelle `rw` ist. Er wird nur dann erzeugt (`is_needed(options)`),
  sodass ein Eintrag, der ihn nicht nutzt, keine zusätzlichen Anfragen stellt.
- Die Standardquelle des Trockenzählers ist `rw`, bestehende Installationen
  behalten aber `rs`: Der Konfigurationseintrag ging auf Version 1.2, und
  `async_migrate_entry` schreibt `dry_streak_source: "rs"` in jeden Eintrag der
  Version 1.1, dem es fehlt.
- Wenn er erzeugt wird, ist der :00-Lauf von `rw_10min` dieselbe Datei, die
  auch `rw` abruft; beide laufen über den `DownloadCache` des Eintrags, sie
  wird also nur einmal heruntergeladen.

## Verworfene Alternativen {#alternatives-turned-down}

- **Ein Sensor für die gleitende RW-Stunde.** Als „last 60 min“ läge er 28–38
  min zurück, wo RS 4–9 min zurückliegt, und für die Genauigkeit der
  Niederschlagsmesser gibt es `Precipitation previous hour`. Eine Vorabversion
  hatte dafür eine Option `rw_last_hour_mode`; sie wurde nie ausgeliefert, und
  ein gespeicherter Wert wird ignoriert.
- **Summen aus den 10-Minuten-Läufen.** Aufeinanderfolgende Läufe überlappen
  sich um 50 Minuten, ihre Summe zählt also jede Stunde sechsmal. Die Summen
  und ihr Durchgang über verpasste Veröffentlichungen bleiben auf dem
  stündlichen Terminraster von `rw`, ebenso die Korrektur des Trockenzählers
  beim Start für die Zeit, in der Home Assistant nicht lief.
- **Rückfall auf die andere Quelle**, wenn die gewählte ausfällt: Die Entität
  folgt stattdessen der Verfügbarkeit ihres Coordinators.
