# 0.3.9.26 – lokale Validierung

412 Tests: 408 erfolgreich, dieselben 4 bestehenden übersprungen.
Befehl: `python -m unittest discover -s tests -p 'test_*.py'`.

15 neue Profiler-Tests prüfen:
- Inaktiv: keine Clock-Reads und F10 nicht konsumiert; Arming installiert keine Wrapper.
- Exakte Verschachtelung/Eigenzeit ohne Doppelzählung; Exceptions und Stackbalance.
- Ereignislimit, gebundene Sample-/Intervallzahl und JSON-Schema ohne erfundene FPS.
- Zeitlich begrenzte Detail-Wrapper, Native-Read-Anzahl/Bytes und exakte Wiederherstellung.
- Andere Threads/Owner und Aufrufe außerhalb Omni-Roots werden nicht mitgemessen.
- Aufgeschobener Stop innerhalb eines Calls; Fremd-Replacements werden nicht überschrieben.
- Teilweise Installation und Datei-Schreibfehler stellen die Wrapper wieder her.
- Manuelles F10-Ende, Label-/Thread-/Session-Guards und leere Statistik.
- Echter Loader: Console -> Arm -> F10 -> 600 tatsächliche Gameplay-Frame-Einstiege
  -> automatische Completion, 1200 gemessene bound-Aufrufe und 600 Reads -> Restore.
  Der übrige Gameplay-Body und die SDK-/Native-Blätter werden in diesem Wiring-
  Test substituiert; es werden weder native Detours ausgeführt noch FPS gemessen.

Die bestehende ADS-/Reticle-/Omni-/Cleanup-Testserie besteht. Native Templates,
Build-Guards und Gameplay-Pipeline bleiben erhalten. Dieser lokale Nachweis
prüft Instrumentierung und Python-Logik; Performance-Werte und .25-Reticle-
Darstellung sind im Spieltest noch offen.
