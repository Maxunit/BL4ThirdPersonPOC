# 0.3.9.30 – lokale Validierung

466 Tests: 462 erfolgreich, dieselben vier bestehenden übersprungen.

5 neue Tests (`ExitFacingTests` in `tests/test_omni_bind_hitch_0_3_9_29.py`):
- Stehendes oder absetzendes Fahrzeug (Rückwärts-Rauschen, Mini-Vektoren, null)
  behält den Fahrzeug-Yaw.
- Fahrt vorwärts und zügig rückwärts nutzt die Fahrtrichtung.
- Nach dem Anhalten gilt wieder der Fahrzeug-Yaw.
- Genau eine Trace-Zeile beim Einsteigen.
- Ein fehlschlagender Trace-Wert ergibt `?`, keine Exception.

Die Native-Stubs laufen unter Linux nicht; die tatsächliche Ausstiegsrichtung
zeigt erst der Spieltest.
