# 0.3.9.28 – lokale Validierung

443 Tests: 439 erfolgreich, dieselben vier bestehenden übersprungen.
Befehl: `python -m unittest discover -s tests -p 'test_*.py'`.

14 neue Tests (`tests/test_omni_callback_scope_0_3_9_28.py`):

- Kostenbudget: echter Omni-Code in der zählenden Fake-Welt, Stand und Hocke.
  Grenzen pro Update u. a. 2 Runtime-Auflösungen, ≤ 6 bzw. 8 ReadProcessMemory,
  ≤ 28 bzw. 32 UFunctions, höchstens 2 volle Mapping-Scans pro 600 Updates.
  Gegen .27 schlägt das Budget fehl (30 / 28 / 48 / 20).
- Callback-Scope: außerhalb jedes `bound()` voll; im Callback eine Auflösung;
  gewechselter Localplayer im nächsten Callback erkannt; Fehler-Callback und
  `finish()` verwerfen Objekte und Werte.
- Memoisierte Getter: ein Dash-Read pro Callback; Game-Write verwirft den Wert.
- Native-Audit: erstes Update und Resume prüfen alle Slots; jeder Slot innerhalb
  einer Periode, höchstens zwei pro Update.
- Tasten: ohne oder mit fehlerhafter Einordnung beide Abfragen; Knopf nur
  digital, Achse nur analog, Button-Achse beide; gedrückt/bewegt/NaN unverändert.
- Stillstand: kein Handler-Check und kein Native-Read in der Ground-Vorbereitung.

Angepasst: `test_native_validation_failure_during_scope_still_stops_session`
prüft die Erkennung jetzt innerhalb einer Audit-Periode (siehe Changelog).
Versionsprüfungen in zwei Tests auf 0.3.9.28.

Diese Tests prüfen Python-Logik und SDK-Zugriffszahlen, keine Zeiten und keine
FPS. Native-Detours laufen unter Linux nicht. Spieltest und F10-Messung stehen aus.
