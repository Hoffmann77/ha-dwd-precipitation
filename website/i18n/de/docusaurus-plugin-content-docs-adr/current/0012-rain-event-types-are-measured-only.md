# 0012 — Regenereignisse haben eine Niederschlagsart erst, wenn sie gemessen ist

Status: angenommen (2026.11.0)

## Kontext {#context}

Der Pull Request eines Beitragenden (#103) fügte eine Regenwarnung hinzu, die
die Art des kommenden Niederschlags nennt, und, wenn die eigene Zelle des
Standorts keine hatte, die Art des nächsten Niederschlags im Umkreis von 5 km.
Die Art ist in den Regenereignissen nützlich: Ein Blueprint kann Schnee,
Graupel oder Hagel melden statt nur „Regen“.

Was der DWD dafür anbietet:

- **HymecNG**, die Klassifikation der Niederschlagsart, die die Integration
  schon liest, ist eine Datei alle 5 Minuten für einen einzelnen Zeitpunkt
  (`startdate` gleich `enddate`). Sie hat keine Vorhersage. OpenData hält
  48 Stunden davon vor (577 Dateien am 21. Okt. 2026).
- **RADVOR** (RV, RS) sagt Mengen vorher, keine Arten.
- Vorhergesagte Arten gibt es nur in ICON-D2 (GRIB2, das eccodes braucht, eine
  Abhängigkeit, die die Integration nicht aufnimmt) und MOSMIX
  (Punktvorhersagen für Stationen, stündlich): andere Produkte auf anderen
  Skalen, keine Art für einen 5-Minuten-Schritt der Kurzfristvorhersage.

## Entscheidung {#decision}

- Jeder gemessene Schritt bekommt die HymecNG-Art des Zeitpunkts, an dem er
  endet, also der HymecNG-Veröffentlichung zur selben Zeit wie die
  RV-Veröffentlichung, deren Analyse er ist. Der HymecNG-Koordinator gibt jede
  Veröffentlichung, die er übernimmt, an die Ereignisverfolgung, meist bevor RV
  dieselbe übernimmt (HymecNG wird nach 3 min abgerufen, RV nach 4 min 10 s,
  jeweils plus höchstens 30 s Jitter). Die Ereignisverfolgung hält die Arten
  nach dem Zeitpunkt des Schritts fest; die Reihenfolge, in der beide
  ankommen, spielt daher keine Rolle, und eine Art, die nach RV ankommt,
  erscheint ab der nächsten Veröffentlichung, da die Ereignisse bei jeder
  Veröffentlichung neu berechnet werden (ADR 0006).
- Eine verpasste Art wird in derselben Hintergrundrunde wie verpasste
  Analysen abgerufen, nach ihnen, da erst dann feststeht, welche Schritte nass
  sind: nur nasse Schritte, nur innerhalb der veröffentlichten Stunde, die
  neuesten zuerst, mit demselben Zeitbudget.
- Veröffentlicht als `observed.types` (nasse gemessene Schritte je Art) und
  `type` (die des letzten nassen gemessenen Schritts), bei laufenden und
  beendeten Ereignissen. Die Arten sind die des DWD, unverändert: Ein nasser
  Schritt, den HymecNG `no_precipitation` nennt, wird so gezählt. Ein nasser
  Schritt ohne Art wird nicht gezählt.
- **Nichts wird geschätzt.** Ein bevorstehendes Ereignis hat `type: null`. Die
  Art einer Nachbarzelle, eine regionale Zusammenfassung, eine Regel nach der
  Temperatur oder die vom letzten Ereignis übernommene Art werden alle nicht
  verwendet.
- Die Ansicht bleibt bei `schema: 1`, da nur Felder hinzukommen, und der
  Speicher bleibt bei Version 1: Ein vorher gespeicherter Zustand wird als
  „keine Art bekannt“ gelesen.

## Folgen {#consequences}

- Eine Warnung vor der Art, bevor der Regen ankommt, kann nicht von dieser
  Integration kommen. Ein Blueprint kann die Regenereignisse mit eigenen
  Quellen verbinden (einer Wetter-Entität, einem Temperatursensor), in eigener
  Verantwortung.
- Die Art erscheint mit dem ersten gemessenen nassen Schritt, etwa 5 Minuten
  nach Beginn des Regens.
- Der Speicher hält eine Art je Schritt, so lange wie die gemessenen
  Schritte, auch für trockene Schritte, da eine Art ankommt, bevor feststeht,
  ob ihr Schritt nass ist.

## Verworfene Alternativen {#alternatives-turned-down}

- **Die nächste Art im Umkreis von 5 km** (#103). Regen, der in einer Stunde
  erwartet wird, ist meist Dutzende Kilometer entfernt, und die nächste Zelle
  muss nicht die sein, die auf den Standort zuzieht.
- **Die häufigste Art der nassen Zellen im Umkreis von 30-50 km.** Plausibel,
  da die Art vor allem vom Temperaturprofil abhängt, das sich langsam ändert,
  aber es ist eine Schätzung: falsch nahe der Schneefallgrenze, im Bergland,
  hinter einer Front und bei Hagel und Graupel, die örtlich sind. Die
  Integration stünde für ihre Genauigkeit ein.
- **ICON-D2 oder MOSMIX.** Das erste braucht GRIB2-Dekodierung, das zweite
  ist die stündliche Vorhersage einer Station. Beides wäre ein eigenes
  Vorhersageprodukt, nicht die Art eines Ereignisses der Kurzfristvorhersage.
- **Den aktuellen Wert des HymecNG-Koordinators lesen, wenn die
  RV-Veröffentlichung verarbeitet wird.** Welche der beiden zuerst übernommen
  wird, ist nicht garantiert, und eine verpasste HymecNG-Veröffentlichung wäre
  nicht von einer verspäteten zu unterscheiden. Nach dem Zeitpunkt des
  Schritts festzuhalten lässt nichts, was sich überholen könnte.
