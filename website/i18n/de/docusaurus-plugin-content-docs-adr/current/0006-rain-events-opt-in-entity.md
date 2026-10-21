# 0006 — Regenereignisse sind eine eigene Opt-in-Entität, bei jeder Veröffentlichung neu berechnet

Status: angenommen (2026.11.0); der Teil zum Opt-in ersetzt durch
[0012](0012-rain-warnings-as-subentries.md), das die Ereignisverfolgung auch
für Regenwarnungen laufen lässt

## Kontext {#context}

Der Regenereignis-Tracker gibt eine Ansicht (Schema 1) aus, auf die Blueprints
angewiesen sind: ein paar KB, die sich mit jeder Veröffentlichung ändern. Seine
gemessenen Schritte sind RV-Analysen (Vorlaufzeit 0); nur die Veröffentlichung,
zu der eine Analyse gehört, enthält sie. Eine verpasste Veröffentlichung
hinterlässt daher eine Lücke, die die Integration füllt, indem sie diese
Analyse später abruft.

## Entscheidung {#decision}

- **Eigene Entität.** In Vorabversionen hing die Ansicht als Attribut
  `rain_events` an `Precipitation expected`; ein binäres Flag ist dafür der
  falsche Ort. Sie ist der Sensor `Rain events`, auf dessen Zustand
  (`ongoing` / `upcoming` / `none`) ein Blueprint auslösen kann.
- **Opt-in.** Die Option `rain_events` (Erweiterte Optionen, standardmäßig
  aus) schaltet das alles: kein Tracker, keine Anfragen zum Nachholen, kein
  Speicher. Keine Version vor 2026.11.0 hatte sie, also ist sie auch bei
  bestehenden Installationen aus. Ausschalten entfernt die Entität aus der
  Registry und löscht den Speicher, sodass erneutes Einschalten sauber neu
  beginnt.
- **Neu berechnet, nicht aufsummiert.** Jede Veröffentlichung baut die
  Zeitachse aus den behaltenen gemessenen Schritten neu auf und berechnet die
  Mengen und Spitzen jedes Ereignisses neu. Das weicht bewusst von den
  inkrementellen Akkumulatoren der Spezifikation ab: Die Werte sind dieselben,
  aber ein spät nachgeholter Schritt kann nie doppelt gezählt werden, und
  `observed` kann nie sinken.
- **Erst nachholen, dann zuordnen, im Hintergrund.** Erst zu aktualisieren und
  danach nachzuholen kann Ereignis-IDs vertauschen und `forecast_at_onset`
  verlieren, wenn es in einer Zeit regnete, in der Home Assistant nicht lief.
  Eine Veröffentlichung mit nachzuholenden Schritten führt Nachholen,
  Aktualisieren und Ausgeben daher als eine Hintergrundaufgabe aus. Die
  Einrichtung wartet auf die erste Aktualisierung von RV und darf nicht auch
  noch auf das Nachholen warten; solange behält der Sensor die Ansicht, die er
  vorher zeigte. Spätere Veröffentlichungen reihen sich hinter eine laufende
  Runde ein.
- **Ansichten werden gespeichert.** Ein Ereignis mit `unseen` wird aus seiner
  letzten Ansicht erneut ausgegeben, und die gespeicherte Ansicht beantwortet
  dieselbe Veröffentlichung nach einem Neustart, ohne sie zweimal zu
  verarbeiten.
