# BL4ThirdPersonPOC 0.3.9.1 – Korrekturen aus dem Spieltest 0.3.9.0

Basis ist 0.3.9.0. Beim Spieltest liefen die Punkte 0 bis 9 durch, mit Ausnahme von Respawn und Save/Load. Native Templates und RVAs sind unverändert.
**Noch nicht im Spiel getestet**, siehe `TESTPLAN_0.3.9.1.md`.

## Befund aus den Logs
- **Respawn und Save → Hauptmenü → Laden:** In beiden Logs fehlt die Zeile `CAMERA_LIFECYCLE_ARMED`.
  - Die vorhandene Kamera-Reparatur der Hauptmod wird nur über ClientRestart gestartet, und dieser Start fand nicht statt.
  - Dadurch blieb BL4 in der Default-Kamera (FPS), während die Mod weiter `_third_person_enabled=True` und einen alten Stack-Eintrag führte.
  - Das erste F5 schaltete dann ein unsichtbares TPS „aus“, deshalb waren zwei Tastendrücke nötig.
- Omni schreibt weder Kamerazustand noch Lifecycle, deshalb ist der Zusammenhang mit 0.3.9.0 unwahrscheinlich. Ob die Lücke schon in 0.3.8.17 bestand, ist nicht belegt.
- **A/S/D-Slides:**
  - Die Hauptmod setzt `_slide_active` zurück, bevor BL4 die Kamera aus dem Slide-Modus zurückgibt.
  - Omni hat diese kurze Default-/Slide-Kamera bisher als Sonderzustand pausiert und damit die native TurnState-Neutralisierung ausgeschaltet.
  - Bei gehaltenem Crouch hielt die Freigabesperre diese Pause noch länger.
  - In dieser Zeit drehte das Spiel den Körper zur Blickrichtung zurück. Bei W-Slides fällt das nicht auf, weil Blick- und Slide-Richtung gleich sind.

## Änderungen
1. **`tps_recovery.py`** (neu, ohne Hooks und ohne native Writes)
   - Gilt für den Fall: TPS ist gewünscht, aber die Default-Kamera ist seit mindestens 0,75 s gesetzt und stabil.
   - Gesperrt bei ADS-, Slide-, Leiter-, Fahrzeug-, Shop-, Menü- und FFYL-Routen.
   - Startet dann die vorhandene Kamera-Reparatur mit dem Grund `tps_desync`. Diese entfernt einen veralteten Owner (bei leerem Stack ohne blindes Pop) und setzt TPS neu.
   - Begrenzung: höchstens 3 Versuche pro Episode im Abstand von 3 s.
   - Die eigene Anfrage wird aufgelöst, sobald TPS auf anderem Weg zurückkommt, und verworfen, wenn ein Fahrzeug übernimmt.
2. **F5 bei sichtbarer FPS-Kamera und gewünschtem TPS** repariert jetzt (`TPS_TOGGLE_REPAIR`), statt auszuschalten.
3. **Diagnose:** Jeder ClientRestart schreibt `CLIENT_RESTART_SEEN controller_local=… pawn_matches=… tps_enabled=…`. Damit zeigt der nächste Test, warum die Reparatur nicht startete.
4. **Omni Slide-Ausgang:**
   - Neues Zeitfenster `SLIDE_EXIT`. Es beginnt, wenn der Slide-Flag zurückgesetzt wird, und endet, sobald die Hauptmod eine stabile ThirdPerson-Kamera bestätigt (`_slide_camera_recovery_pending` wird zurückgesetzt).
   - In diesem Fenster bleibt die TurnState-Neutralisierung aktiv. Der Körper hält die Slide-Richtung (bei Restschwung die Bewegungsrichtung, maximal 540°/s) und wird jedes Update gegen native Rückdrehung zurückgesetzt.
   - Kampf hat weiterhin Vorrang. Der Ausgang hat Vorrang vor CROUCHED.
   - Im Diagnosemodus zeigt `slide_exit_cycles` die gemessene native Abweichung.
5. **`bl4tps_actions all`** listet alle Mapping-Zeilen mit vollem Pfad, auch außerhalb von `/Game/GameData/Input/EnhancedInput/`. In der Ausgabe von 0.3.9.0 fehlte E komplett.

## Tests
- 96 Python-Tests, alle grün unter Python 3.12 und 3.13. Neu sind unter anderem:
  - Ende-zu-Ende über den echten Lifecycle-Code: Default mit veraltetem Owner → genau ein Push, kein blindes Pop.
  - F5-Reparatur
  - Slide-Ausgang: Zeitfenster, Halten gegen native Abweichung, Vorrang des Kampfes
  - Vollständige Mapping-Liste
