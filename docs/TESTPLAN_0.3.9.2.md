# Testplan 0.3.9.2 (gezielter Nachtest; ersetzt 0.3.9.1)

Installation wie bei 0.3.9.0: die `.sdkmod` ersetzen und `__pycache__` löschen. 0.3.9.1 muss nicht separat getestet werden. Omni bleibt an. Für die Punkte 2 und 3 bitte `bl4tps_omni diag on` einschalten.

## 1. Interaktions-Aktion finden
1. Im Spiel vor eine Kiste oder einen Automaten stellen, sodass der Interaktions-Hinweis sichtbar ist.
2. `bl4tps_actions all` eingeben und die komplette Ausgabe schicken.
3. Wichtig ist jede Zeile, in der `E` oder `Gamepad_FaceButton_Left` vorkommt.

## 2. Tod und Respawn
1. Sterben, Respawn abwarten und nichts drücken.
2. Erwartet: Die Respawn-Kamerafahrt endet direkt an der Position der aktiven TPS-Kamera. Der Übergang ist ein modifizierter Blend-In auf dem Kamerapfad, ohne Zwischenstopp in FPS und ohne nachträgliches Umschalten.
3. In der Konsole sollte Folgendes stehen:
   - `CAMERA_LIFECYCLE_ARMED reason='client_restart'`. Davor kommt entweder ein ClientRestart oder neu `[BL4ThirdPersonPOC.TPSRecovery] RESPAWN_CAMERA_SEEN …`.
   - Danach `[BL4ThirdPersonPOC.Respawn] early_tps_push {…}` und `[BL4ThirdPersonPOC.Respawn] target_settled …`.
4. Nicht erwartet:
   - `[BL4ThirdPersonPOC.Respawn] DECLINED …`
   - Ein kurzer FPS-Moment, auf den eine normale TPS-Reparatur folgt (`CAMERA_LIFECYCLE_REPAIR_START`).
   - Beides bedeutet, dass der Respawn-Pfad abgelehnt hat und nur die Notlösung griff. Dann bitte die DECLINED-Zeile schicken.
5. Bitte alle Zeilen mit `CLIENT_RESTART_SEEN` mitschicken.

## 3. Save → Hauptmenü → Laden
1. Erwartet: Nach dem Laden kehrt TPS ohne F5 zurück.
2. Falls doch FPS bleibt, schaltet **ein** F5-Druck TPS ein (`TPS_TOGGLE_REPAIR`).
3. Bitte die Zeilen `CLIENT_RESTART_SEEN` und alle `TPSRecovery`-Zeilen schicken.

## 4. Slides in alle Richtungen
1. Sprint und Slide nach vorne, links, rechts und hinten, jeweils einmal mit gehaltenem und einmal mit losgelassenem Crouch.
2. Erwartet: Nach dem Slide zeigt der Körper weiter in Slide- bzw. Bewegungsrichtung und dreht sich nicht zur Kamera zurück.
3. Danach in alle Richtungen loslaufen. Der Körper folgt wie gewohnt der Bewegung.
4. Danach `bl4tps_omni report` eingeben und die JSON schicken. Sie enthält `slide_exit_cycles` mit der gemessenen nativen Abweichung.

## 5. Kurze Regression
- F5 hin und her im normalen Spiel: FPS ↔ TPS muss weiterhin mit **einem** Druck wechseln.
- Sniper-ADS in FPS, Leiter, Fahrzeug und Shop dürfen **kein** `TPSRecovery` auslösen.
- FFYL mit Second Wind wie bisher.

## Was zurückschicken
- Die Konsolenzeilen mit `TPSRecovery`, `CLIENT_RESTART_SEEN`, `TPS_TOGGLE_REPAIR`, `SLIDE_EXIT_HOLD` und `CAMERA_LIFECYCLE`.
- Die Ausgabe von `bl4tps_actions all`.
- Die JSON aus `sdk_mods/settings/BL4ThirdPersonPOC_reports/`.
