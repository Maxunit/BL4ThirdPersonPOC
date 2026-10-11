# 0.3.9.27 – lokale Validierung

429 Tests: 425 erfolgreich, dieselben vier bestehenden übersprungen.
Befehl: `python -m unittest discover -s tests -p 'test_*.py'`.

17 zusätzliche Tests prüfen:

- Zwölf Input-Verbraucher: eine Mapping-Anzahlprüfung statt zwölf, weiterhin
  eine physische Key-Aufnahme; Snapshot-Kopien können sich nicht beeinflussen.
- Default-Modus des gemeinsamen Lesers behält sofortige Mapping-Anzahlchecks.
- Remap/Anzahländerung beim nächsten Callback; explizite Refresh-Invalidierung.
- Gewechselter Controller/PlayerInput und abgelaufene WeakPointer werden auch
  bei vorhandener Aufnahme abgelehnt.
- Echter Gameplay-Frame-Einstieg mit Fehler: Snapshot wird im finally geleert.
- Normaler Visual-Schritt läuft ohne volle Diagnose weiter zur Body-Pipeline.
- Diagnosepfad verarbeitet weiter Visual-Zeilen; tatsächlicher AimOffset-
  Capture enthält Animations-, Node- und Richtungsdaten wie zuvor.
- Alle 15 Animationseingaben sowie AimOffset-Kanal/Key/Alpha/Weight:
  ungültige Werte stoppen, bevor Body-Writes laufen; Bool-Werte sind zulässig.
- Abgelaufene Mesh/Anim/Pawn-Referenzen, gewechselte Runtime-/Movement-/Mesh-/
  Anim-Owner und abweichende Anim-Adresse schlagen weiterhin fehl.
- Kompakter Lifecycle-Zustand bleibt für Handoffs verfügbar; Beschreibungen
  entstehen an Zustandskanten. Eine Runtime-Auflösung im Special-State-Schritt;
  der nächste Schritt erkennt einen gewechselten Localplayer erneut.

Die bisherige ADS-, Hybrid-Reticle-, Omni-, Fahrzeug-, Wurf-, Cleanup- und
Profiler-Serie besteht weiterhin. SDK-Stubs und Linux-Tests führen keine BL4-
Detours aus. Runtime-FPS, Native-Timing und visuelle Darstellung sind erst im
Spiel zu validieren. Aus diesen Tests wird kein FPS-Gewinn abgeleitet.

Produktion geändert: Loader-Version, Input-Leser, Omni-Session, Animation,
Diagnostics, Profiler und das neue Modul visual_guard. Sämtliche Native-
Templates und Build-/Byte-/Hash-Guard-Implementierungen sind gegenüber .26
bytegleich. Der installierbare Build wird aus diesem geprüften Quellordner
erstellt; Cache-Dateien sind ausgeschlossen.
