# BL4ThirdPersonPOC 0.3.9.2 – Respawn-Kamerafahrt endet in TPS

Basis ist 0.3.9.1, das intern geblieben ist und nicht getestet werden muss. **Noch nicht im Spiel getestet**, siehe `TESTPLAN_0.3.9.2.md`.

## Richtigstellung zu 0.3.9.1
- Nach dem Respawn soll die Respawn-Kamerafahrt per modifiziertem Blend-In an der aktiven TPS-Kameraposition enden.
- Das leistet der vorhandene Respawn-Pfad `respawn_camera.py`: Er pusht TPS während des nativen Default-Übergangs mit der Restdauer des Blends.
- Der Pfad läuft aber nur innerhalb eines `client_restart`-Lifecycles. Dieser wurde im Test 0.3.9.0 nie gestartet, im Log fehlt `CAMERA_LIFECYCLE_ARMED`.
- Die Notlösung aus 0.3.9.1 hätte erst nach der Kamerafahrt in FPS repariert. Das ist nicht das gewünschte Verhalten.

## Änderung
- Neu in `tps_recovery`: `arm_respawn_handoff`.
- Wenn BL4 `RespawnCamera` zeigt, TPS gewünscht ist und noch kein Lifecycle läuft, startet es genau den `client_restart`-Lifecycle, solange die RespawnCamera noch aktiv ist. Das passiert einmal pro Respawn.
- `respawn_camera.py` übernimmt dann unverändert:
  - RespawnCamera erkennen
  - Default-Übergang mit 3,5–4 s Blend erkennen
  - TPS mit der Restdauer pushen
  - `target_settled`
- Ein bereits durch ClientRestart gestarteter Lifecycle wird nicht angefasst. Fahrzeug, Native-Fehler und FFYL-Übergang sperren.
- Die Notlösung für eine stehende Default-Kamera bleibt das letzte Mittel für alle anderen Pfade, etwa Save/Load. Während eines laufenden Respawn-Lifecycles bleibt sie gesperrt.

## Tests
- 100 Python-Tests, darunter ein neuer Test für den Respawn-Start (einmal pro Respawn, Sperren).
- Ein Ende-zu-Ende-Lauf über die echte Lifecycle-Logik bestätigt: RespawnCamera erreicht `respawn_camera.py` mit dem Grund `client_restart`.
- Außerhalb des Spiels lehnt der native Blend-Leser ab (kein Spielspeicher). Im Spiel prüft er Build und Layout.
