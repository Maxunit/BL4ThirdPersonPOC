# Testplan 0.3.9.0 (Spieltest)

Reihenfolge einhalten: Die Punkte bauen aufeinander auf. Bei einem Fehler bitte abbrechen und den Konsolen-Ausschnitt sowie die JSON-Reports schicken.

## 0. Installation
1. BL4 komplett beenden.
2. In `sdk_mods` die alte `BL4ThirdPersonPOC.sdkmod` durch die neue ersetzen.
3. Alte Lab-Dateien **löschen**: `player_omnidirectional_gameplay.py` und den Ordner `bl4_omnidirectional`. Beide nutzen denselben Statusschlüssel und würden sich mit dem integrierten Feature in die Quere kommen.
4. Alle `__pycache__`-Ordner in `sdk_mods` löschen und das Spiel starten.

## 1. Build-Gate
- In der Konsole `bl4tps_build` eingeben.
- Erwartet: `reviewed=True label='steam-2026-09-14' store=steam`.
- Falls `INACTIVE_UNREVIEWED_BUILD` erscheint, bitte die komplette Zeile schicken. Die Mod bleibt dann absichtlich komplett inaktiv.

## 2. Regression ohne Omni (Feature ist standardmäßig aus)
- F5 TPS, F6 Schulter, F7 Menü, ADS mit Maus und Pad, Interaktion E/Viereck, Fahrzeug rufen/fahren/aussteigen, FFYL, Ground Slam.
- Erwartet: alles wie bei 0.3.8.17.

## 3. ADS folgt der Spielbelegung
1. Im Spielmenü ADS/Zoom auf eine andere Maustaste oder Taste legen (z. B. Maus-Seitentaste oder C) und das Menü schließen.
2. Konsole prüfen. Erwartet: `[BL4ThirdPersonPOC.ActionKeys] REBOUND role=ads device=kbm RightMouseButton -> …`.
3. In TPS mit der neuen Taste zielen: Hybrid-ADS, Rückkehr und Waffenwechsel testen.
4. Belegung zurücksetzen. Erwartet: erneutes REBOUND zurück auf `RightMouseButton`.
5. Pad: Mit L2/LT muss ADS unverändert funktionieren.

## 4. Interaktions-Aktion identifizieren (einmalig)
- Im Spiel, nicht im Hauptmenü, `bl4tps_actions` eingeben und die komplette Ausgabe schicken.
- Daran sehen wir den Namen der Use-Aktion und können die Interaktion danach ebenfalls auf die Spielbelegung umstellen.

## 5. Omni einschalten (Produktionsmodus)
1. F7 → CAMERA MODES → MOVEMENT (EXPERIMENTAL) → TOGGLE. Erwartet: `Omni Movement: ON`. Menü schließen.
2. Kurz normal bewegen und `bl4tps_omni status` eingeben. Erwartet: `running: True`, nach dem Laufen `gameplay_bound: True`.
3. Den bekannten Ablauf wie im Lab durchgehen: Laufen, Sprint, Sprint-Dash, Boden- und Luftdash (auch Tastaturdiagonalen), Crouch und Aufstehen, Slide, Feuern aus Sprint, ADS.
4. Erwartet: gleiches Verhalten wie im letzten Labor-Build, aber **keine** laufenden Warn-Zeilen in der Konsole.
5. Ausschalten (TOGGLE). Erwartet:
   - Anzeige `OFF`, keine Fehler.
   - Der Körper springt **nicht** mehr zur alten Startrotation zurück.
   - Im Produktionsmodus wird keine JSON geschrieben.

## 6. Diagnosemodus
1. `bl4tps_omni diag on` eingeben. Das Feature startet neu, die Statusmeldungen erscheinen wieder als Warnungen.
2. Kurzen Ablauf spielen, dann `bl4tps_omni report` eingeben. Das schreibt einen Snapshot, ohne zu stoppen.
3. `bl4tps_omni off` eingeben. Das schreibt den Abschluss-Report.
4. Die Reports liegen in `sdk_mods/settings/BL4ThirdPersonPOC_reports/`.
5. Danach wieder `bl4tps_omni diag off` eingeben.

## 7. Autostart und Kaltstart
1. Omni an lassen, das Spiel komplett beenden und neu starten, dann einen Spielstand laden.
2. Erwartet:
   - **Kein** `STOPPED_ON_ERROR` beim Laden. Genau dieser Fall ist neu abgesichert.
   - Nach Laden, F5 und Bewegen bindet Omni automatisch.

## 8. Lebenszyklus (bisher ungeprüft)
- TPS → FPS → TPS, Fahrzeug rein und raus, Mantle, Leiter, Greifhaken, Ground Slam.
- FFYL und Second Wind, Tod und Respawn, Fast Travel, Save & Quit mit erneutem Laden.
- Bei einem Fehler meldet die Konsole `STOPPED_ON_ERROR` und es entsteht ein Report. Das Feature bleibt dann aus, bis man es per Menü oder `bl4tps_omni on` wieder einschaltet.

## 9. Mod aus- und einschalten
- Bei laufendem Omni die Mod im Mod-Manager deaktivieren und wieder aktivieren.
- Erwartet: kein `DISABLE_CAMERA_GROUP_RETAINED` und keine `DISABLE_STAGE_ERROR`.

## Was zurückschicken
- Die Konsolenzeilen mit `[BL4ThirdPersonPOC`, `[OmnidirectionalGameplay]`, `ActionKeys` und `BUILD_GATE`.
- Alle JSON-Dateien aus `sdk_mods/settings/BL4ThirdPersonPOC_reports/`.
- Kurze Beschreibung: was erwartet war und was passiert ist.
