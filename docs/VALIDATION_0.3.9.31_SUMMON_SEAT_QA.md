# 0.3.9.31 – lokale Validierung

479 Tests: 477 erfolgreich, 2 übersprungen (Keystone-Assembler nicht installiert).
Zwei Template-Tests, die in .30 mangels Capstone übersprangen, liefen hier mit
und sind grün.

13 neue Tests (`tests/test_summon_seat_0_3_9_31.py`):
- Summon-Datensatz wird im Layout des Getter-Stubs gelesen; alte, fehlende oder
  fremde Datensätze zählen nicht.
- Unsichtbare Figur (kein Fahrer, Actor versteckt, Mesh unsichtbar) mit Kamera
  hinter dem Fahrzeug: genau ein `SetControlRotation` in Update 2, Neigung bleibt.
- Sichtbarer Fahrer: keine Kamera-Änderung.
- Seitliche Lücken (±90°, 45°): keine Kamera-Änderung, auch bei unsichtbarer Figur.
- Ohne Summon-Datensatz: keine Kamera-Änderung.
- Nur kurz unsichtbar (2 Updates): keine Kamera-Änderung.
- Lücken über die ±180°-Grenze werden richtig gerechnet.
- Eine Trace-Zeile pro Einstieg mit Timeline und `turn_frame`; früher Ausstieg
  schließt das Fenster, der nächste Einstieg öffnet ein neues.
- Fehlschlagender Read schließt das Fenster ohne Exception und ohne Write.
- Zu Fuß ohne offenes Fenster kein Zugriff.

Zähl-Umgebung `stand`/`move` unverändert gegenüber .30 (Vehicle-POST ist dort
nicht enthalten; zu Fuß ohne Fenster kommt kein Zugriff hinzu).

Native-Stubs unverändert (Template-Hashes grün). Ob der Lichtschütze erkannt wird
und sich mit der Kamera ausrichtet, zeigt erst der Spieltest.
