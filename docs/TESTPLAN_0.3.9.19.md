# 0.3.9.19 QA

## Installation

Spiel vollständig beenden. Alte Mod-Dateien und zugehörigen __pycache__ entfernen.
`dist/BL4ThirdPersonPOC.sdkmod` nach `sdk_mods` kopieren. Keine entpackte zweite
BL4ThirdPersonPOC-Version daneben belassen. Keine der bisherigen A/B-Proben arming.

Omni und die vorhandene kamera-relative Fahrzeugsteuerung einschalten. Hybrid ADS
ist für diese QA gesperrt. Kamera-/Aim-Margin-Einstellungen bleiben erhalten.

## Zuerst: frischer Einstieg

1. Nach frischem Spielstart und geladenem Save kurz mit Omni laufen.
2. Das eigene Fahrzeug während einer von der Kamera abweichenden Bewegungsrichtung
   herbeirufen. Besonders seitwärts und rückwärts relativ zur Kamera prüfen.
3. Das Fahrzeug soll in Bewegungsrichtung stehen. Die Kamera soll keinen ungewollten
   Richtungssprung machen. Bei gehaltenem Bewegungseingang soll es zu Beginn nicht
   kurz entgegen der gewünschten Richtung fahren oder kreiseln.
4. Mit dem bisher gemessenen Fahrzeug beginnen; weitere Fahrzeugtypen anschließend
   separat prüfen. Nicht unterstützte Layouts dürfen keine ungeprüften Writes erhalten.

## Ausstieg und Luft

1. Geradeaus, seitwärts relativ zur Kamera und rückwärts fahren; jeweils aussteigen.
2. Die anfängliche Körperausrichtung soll zur zuletzt bewegten Fahrzeugrichtung
   passen. Im Stand soll die zuletzt beobachtete Richtung erhalten bleiben.
3. Im Katapultmoment die Bewegungsrichtung wechseln. Omni soll vor der Landung frei
   drehen können. Abwurfhöhe, Bogen und Geschwindigkeit sollen sich nicht verändern.
4. Landen und weiterlaufen. Ein-/Ausstieg zweimal wiederholen und die Ruckler beurteilen.

## Neuaufbau und Regression

- Zwei Fast Travels durchführen; bei Ankunft und beim Weiterlaufen auf Ruckler achten.
  Den bereits beobachteten kurzen FPS→TPS-Kamerawechsel separat melden; dafür enthält
  diese Build keinen gezielten Kamerafix.
- Nach einem ohnehin passierenden Tod den Respawn-Übergang beobachten. Kein absichtlicher
  Respawn-Test nötig.
- ADS, beide Schultern, Waffenwechsel, Sprint→Feuer, Sprint→Slide und freie Fallrotation.
- Granaten und tragbare Throwables: Ausrichtung sowie die akzeptierte Animations-Haltephase.
- Omni aus-/einschalten, auch nach Fahrzeugnutzung. TPS/FPS wechseln. Mod einmal regulär
  deaktivieren/aktivieren. Keine verbleibenden Eingriffe oder Cleanup-Fehler.
- Kamera-relative Fahrzeugsteuerung aus-/einschalten: bestehendes Fahrverhalten soll
  erhalten bleiben. Der neue Einstiegspfad ist für die eingeschaltete Steuerung geprüft;
  die Ausstiegs-/Luftübergabe gehört unabhängig davon zu Omni.

## Bei Auffälligkeiten

`bl4tps_omni report` speichert den laufenden gewöhnlichen Omni-Report. JSON und den
passenden SDK-Log-Ausschnitt senden, dazu Fahrzeugtyp, Bewegungsrichtung und Zeitpunkt.
`bl4tps_omni status` zählt jetzt auch die separat besessenen Fahrzeug-Patches.
Ein Cleanup-Konflikt darf fremde Bytes nicht überschreiben; Owner bleibt für einen
erneuten `bl4tps_omni off`-Versuch erhalten.
