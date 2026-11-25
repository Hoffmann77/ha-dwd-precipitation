# 0014 — Der Regenverlauf wird aus Gelesenem behalten und nur aus dem aufgefüllt, was der DWD noch bereithält

Status: angenommen (2026.12.0)

## Kontext {#context}

Blueprints, die Regen über viele Stunden beurteilen (die Dauerregen-Warnungen
des DWD betrachten 6 bis 72 Stunden, die zu jedem Zeitpunkt bis zu zwei
Stunden voraus enden können), brauchen den Regen jeder vergangenen Stunde am
Ort. Die Integration veröffentlichte nur den neuesten Wert jedes Produkts:
eine RW-Stunde, eine laufende Summe ohne Werte je Stunde und die letzten 60
Minuten gemessener Radarschritte bei `Regenereignisse`. RW kommt etwa 28
Minuten nach der Stunde, daher endete kurz vor der nächsten die neueste
RW-Stunde bis zu etwa 85 Minuten vor dem neuesten Radarschritt, und 25 dieser
Minuten standen in keinem von beiden.

Blueprints können das nicht selbst behalten: Ein Template-Sensor, der jeden
RW-Wert festhält, verpasst jede Stunde, in der Home Assistant aus war, so wie
es ein Bericht-Blueprint für seine angeeichte Nachbetrachtung tat.

## Entscheidung {#decision}

- **Behalten, nicht erneut abgerufen.** Der RW-Koordinator behält jede volle
  Stunde, die er liest, in einem Store pro Eintrag (`HourlyHistory`): die
  Veröffentlichung, die er übernimmt, und jede vergangene Stunde, die ein
  anderer Sensor über `async_fetch_release` herunterlädt (das Nachholen der
  Summe, die Lückenprüfung des Trockenzählers). Eine schon gehaltene Stunde
  wird dort aus dem Verlauf beantwortet statt erneut heruntergeladen. Damit
  ist `RadolanRW.async_fetch_release` mit Absicht der eine Abrufweg mit einer
  Nebenwirkung: Er ist die eine Stelle, über die jeder Abruf einer
  vergangenen Stunde geht.
- **Nur aus dem aufgefüllt, was der DWD noch bereithält.** Mit der
  Abrufoption ruft der Verlauf auch die Stunden ab, die ihm fehlen, die
  neueste zuerst, aber nie weiter zurück, als OpenData sie bereithält
  (`RW_KEPT`, 47 Stunden): Eine Neuinstallation oder ein langer Ausfall ist
  binnen zwei Tagen behoben, für etwa 30 KB pro Stunde, und alles Ältere
  bleibt in `missing`. Ohne die Option wird dafür nichts heruntergeladen.
- **Am RW-Koordinator, nicht an einer Entität.** Die laufende Summe kann
  deaktiviert sein und der Trockenzähler RS zählen; der Verlauf darf von
  keinem der beiden abhängen.
- **Eine eigene Diagnose-Entität** (`Stündlicher Niederschlagsverlauf`),
  kein Attribut von `Niederschlag vorige Stunde`: Diese Entität wird wenige
  Minuten nach einer überfälligen RW-Veröffentlichung nicht verfügbar
  (`unavailable_when_stale`, standardmäßig an), und Home Assistant verwirft
  die Attribute einer nicht verfügbaren Entität, was den Verlauf genau
  während eines DWD-Ausfalls leeren würde. Der Verlauf bleibt verfügbar, und
  sein Zeitfenster endet an der neuesten *fälligen* Stunde, sodass eine
  verspätete Stunde in `missing` steht, statt zu verschwinden. Jede Stunde
  wird mit ihrem Ende veröffentlicht (`hours`), und `null` heißt nur „keine
  Daten für die Zelle“: Eine nicht erhaltene Stunde steht in `missing`, nie
  als `null`.
- **Optional, drei Optionen**: der Sensor, die gespeicherten Stunden (1-168,
  Standard 72) und ob fehlende Daten abgerufen werden dürfen (Standard an).
  Ausschalten löscht den Store, wie bei den Regenereignissen (ADR 0006).
- **Zwei Stunden gemessener Radarschritte, behalten vom
  Regenereignis-Tracker.** `Regenereignisse` veröffentlicht 24 gemessene
  Schritte als `measured`, genug, um bis zur neuesten RW-Stunde
  zurückzureichen. Die Schritte bleiben im Store des Trackers, der auch die
  daraus neu berechneten Ereignisse hält (ADR 0006): Ein eigener Store für
  die Schritte könnte von einem anderen Zeitpunkt wiederhergestellt werden
  als die Ereignisse, die dann schon gezählten Regen verlören. Die längere
  Aufbewahrung nutzt nur `measured`; die Ereignisse sehen weiterhin die
  veröffentlichte Stunde.
- **Spät aufgefüllte Schritte bleiben aus den Ereignissen.** Darf der
  stündliche Verlauf abrufen, holt die Auffüllrunde des Trackers auch
  verpasste Schritte von `measured` nach der neuesten RW-Stunde (ältere deckt
  RW ab), nach den Schritten, die die Ereignisse brauchen. Sie kommen, nachdem
  die Ereignisse ohne sie beurteilt wurden, und werden daher als `late`
  markiert: in `measured` gezeigt, für jede Berechnung der Ereignisse
  unbekannt, sodass sich ein veröffentlichter Beginn oder eine Menge nie
  verschiebt.
- **Schreiben zu einer festen Frist.** Beide Stores schreiben ruhende Daten
  zur `SaveDeadline` des Eintrags, 6 h nach der ersten ungespeicherten
  Änderung, die spätere Veröffentlichungen nicht verschieben: `async_delay_save`
  von Home Assistant startet seinen Timer bei jedem Aufruf neu, sodass eine
  mit jeder Veröffentlichung erneuerte Verzögerung nie vor dem Herunterfahren
  abläuft. Die beiden Stores teilen eine Frist und schreiben gemeinsam,
  viermal an einem trockenen Tag.

## Verworfene Alternativen {#alternatives-turned-down}

- **Die Stunden bei Bedarf abrufen, die ein Blueprint braucht.** Das würde bei
  jeder Auswertung bis zu 72 Dateien herunterladen, und OpenData hält die
  ältesten 24 davon nicht mehr bereit.
- **Der RW-Verlauf als Attribut von `Niederschlag vorige Stunde`.** Verloren,
  sobald diese Entität nicht verfügbar ist (siehe oben), und die Attribute
  würden mit einem Sensor aufgezeichnet, dessen Verlauf Nutzer behalten.
- **Die Radarschritte in einem eigenen Store von RV,** geteilt vom Tracker
  und der vollständigen Reihe gleitender Stunden. Zwei Stores, von
  verschiedenen Zeitpunkten wiederhergestellt, brechen die Neuberechnung der
  Ereignisse, eine regnerische Veröffentlichung würde beide schreiben, und
  der RV-Store könnte nicht aufräumen, ohne den Tracker zu fragen, was ein
  laufendes Ereignis noch braucht.
- **Alle 24 gemessenen Schritte auffüllen.** Bis zu 12 weitere Bereichs-
  abrufe nach jedem Neustart für Schritte, die RW abdeckt und kein Blueprint
  liest.
- **Ein Store für den Verlauf und die Regenereignisse.** Beide werden
  getrennt ein- und ausgeschaltet und löschen ihre eigenen Daten; ein
  beschädigter Teil würde den anderen verwerfen, und jedes Schreiben würde
  beide neu schreiben.
