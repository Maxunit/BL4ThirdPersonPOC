# Ground-Slam-Phasenprobe für 0.3.9.35

Standalone-PyExec, keine neue Mod-Build nötig. Die Probe schreibt keine Kamera-,
Animations- oder Gameplaywerte und verwendet ausschließlich SDK-Lesezugriffe.
Sie belegt den vorhandenen Diagnoseplatz von .35, damit F10, `bl4tps_height off`
und der reguläre Mod-Shutdown auch diese Aufnahme aufräumen.

1. `ground_slam_phase_capture.py` in deinen bisherigen PyExec-Ordner legen.
2. .35 laden, TPS einschalten und am Absprungort bereitstehen. Andere
   Höhenaufnahmen und Omni-Profiler vorher beenden; Omni-Diagnose aus lassen.
3. In F1 `pyexec ground_slam_phase_capture.py` ausführen und F1 schließen.
   Sobald normales TPS ohne Mausmenü verfügbar ist, beginnt die Aufnahme.
4. Etwa zwei Sekunden stillstehen, dann den langen Ground Slam ausführen.
5. Nach dem Aufschlag und der Kamerarückkehr noch drei bis fünf Sekunden
   stillstehen, damit ein längerer Animationsauslauf sichtbar bleibt.
6. Denselben PyExec-Befehl erneut ausführen, oder F10 drücken: Stop und JSON.
7. `ground_slam_phases_<UTC-Zeitstempel>.json` aus
   `SETTINGS_DIR/BL4ThirdPersonPOC_reports` zurückgeben. Der vollständige Pfad
   steht nach `SAVED` in der Konsole. Bei einem Schreibfehler stoppt die Probe
   trotzdem; erneutes PyExec versucht dieselbe Ausgabe nochmals.

Sicherheitsgrenze: drei Minuten einschließlich Startwartezeit oder 16.000
aufgezeichnete Updates. Kein automatisches Ende beim Wechsel zurück zu TPS.
Die Aufnahme endet auch bei Charakterwechsel, ungültiger Referenz,
TPS-Deaktivierung oder Fahrzeugeinstieg.

Je vorhandenem Update: Kameramodus/-übergang, Position, Geschwindigkeit,
MovementMode/CustomMovementMode, Bodenstatus, reflektierte skalare
Slam-/Luft-/Bewegungszustände und aktuelle Montage mit Position. Bis zu 20 Hz:
Kamera-POV, tatsächlich angewendeter Offset, Spine3, Kameraabstand,
Root-Height-/Motion-Zustand. Zustandswechsel enthalten Zeitklammern zwischen
letzter und neuer Beobachtung; `field_schema` zeigt verfügbare Kandidaten.
Fehlende optionale Felder werden nach einem Fehler nicht weiter gelesen.

Die SDK-Lesezugriffe bilden keinen gemeinsamen atomaren Render-Snapshot.
Ein Kameramodus oder Feldname allein beweist weder den exakten Slam-Beginn
noch den physischen Aufschlag oder das Ende der Charakteraktion. Die Probe
soll zeigen, welche Signale im tatsächlichen Spiel miteinander korrelieren.
Ihre zusätzliche Arbeit ist Diagnoseaufwand und keine FPS-Benchmark.

Lokale Prüfung: `python tests/ground_slam_phase_probe_scenario.py` nutzt den
echten Loader und Update-Router mit simulierten SDK-Objekten. Geprüft werden
ein 25 Sekunden langer Slam, voneinander abweichende Charakter-/Kameraenden,
manueller Stop, F10, Shutdown, beide Limits, Fremd-Widget-Filter,
Referenzwechsel, optionale Getter sowie Schreib-/Detach-Fehler mit Wiederholung.
Die Ingame-Signale und Animation müssen mit der Nutzeraufnahme geprüft werden.
