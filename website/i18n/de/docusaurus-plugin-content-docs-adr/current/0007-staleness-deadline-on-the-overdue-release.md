# 0007 — Veraltung ist eine Frist ab der überfälligen Veröffentlichung

Status: angenommen (2026.9.0)

## Kontext {#context}

Solange der DWD nicht veröffentlicht, muss ein zwischengespeicherter Wert
irgendwann nicht mehr gemeldet werden. Die erste Regel maß diese Toleranz ab
der *zwischengespeicherten* Veröffentlichung. Damit musste sie in
Veröffentlichungsintervallen ausgedrückt werden, und sie lief genau dann ab,
wenn ein späterer Abruf fällig war: Der Wert wurde genau in dem Moment
abgeschrieben, in dem der Versuch lief, der ihn hätte wiederherstellen können,
und was zuerst geschah, hing von der Latenz der Event-Loop ab. Deshalb machte
eine routinemäßig verspätete Datei die Sensoren leer und schrieb jedes
einzelne Mal einen ERROR ins Protokoll.

Unabhängig davon wurde `sf_2350` (23:50 Ortszeit) mit
`async_track_utc_time_change` registriert, obwohl sein Terminraster auf der
Ortszeit liegt. Es wurde jeden Tag um so viele Stunden zu spät abgerufen, wie
die Zeitverschiebung beträgt — im Sommer 1,5 h, nachdem seine eigene
Veraltungsfrist schon abgelaufen war.

## Entscheidung {#decision}

- Die Frist beginnt, wenn die Veröffentlichung *nach* der
  zwischengespeicherten auf OpenData hätte sein sollen, und läuft für das
  `OVERDUE_GRACE` des Produkts. Sie beantwortet die Frage „wie lange versuchen
  wir es weiter mit einer Veröffentlichung, die bereits fällig ist“.
- Sie kollidiert nur dann mit dem Abrufraster, wenn `OVERDUE_GRACE` ein
  ganzzahliges Vielfaches von `RELEASE_INTERVAL` ist; ein Test stellt pro
  Produkt sicher, dass es das nicht ist.
- `OVERDUE_GRACE` skaliert nicht mit dem Intervall: Die stündlichen und
  täglichen Produkte geben eine verpasste Veröffentlichung genauso schnell auf
  wie die 5-Minuten-Produkte, denn die Frage ist, wie viel Zeit der DWD zum
  Veröffentlichen bekommt.
- Ein Produkt registriert seinen eigenen Veröffentlichungsplan
  (`async_track_releases()`), sodass das Terminraster und die Uhr, in der es
  gelesen wird, eine einzige Entscheidung sind: Der Einstiegspunkt hatte nur
  die Hälfte davon.
