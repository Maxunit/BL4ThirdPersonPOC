# 0.3.9.38 – lokale Validierung

`python -m unittest discover -s tests -p 'test_*.py' -v`:
574 Tests, 569 bestanden, fünf optionale übersprungen.
Ausgabe: `TEST_OUTPUT_0.3.9.38.txt`.

Der neue Regressionstest wurde zuerst gegen unveränderte .37 ausgeführt.
Bei Kamera-Yaw 0 und Actor-Yaw 180 lieferte der echte Exit-Pipeline-Code
(1,1,1,1,0,0) statt einer einheitlich freigegebenen Gate-Gruppe. Dies beweist
den widersprüchlichen Steuerzustand, nicht den gerenderten Zittereffekt.

Fünf neue Tests prüfen den echten Slam-/Special-Pfad mit SDK-Stubs:
- 90 Exit-Updates halten alle sechs Eingriffsgates geschlossen. Getrackte
  Control-Schreibvorgänge prüfen auch zwischenzeitliches Wiederöffnen;
  read-only Recording darf weiterlaufen, Actor-Setter wird nicht aufgerufen.
- Native Zuständigkeit für Luft-Slam, GroundSlamExit und den eigenen TPS-Blend;
  normale Sprünge, fremde Blends und FPS fallen nicht in diese Ausnahme.
- Frühzeitige Freigabe alter Aim-/Idle-/Turn-/Jump-Gates.
- Aktiver Slam bei sichtbarem ThirdPerson läuft durch echten Special-Pfad,
  ruft keinen gewöhnlichen Air-/Slide-Body-Pfad auf.
- Ruhiger TPS kehrt durch die bestehende Wiederaufnahme in die normale
  Pipeline zurück.

Die bisherigen Free-Look-, ADS-, Fahrzeug-, Root-, Distanz-, Shutdown- und
ausgeführten nativen x64-Tests bestehen. Native Prefixes sind unverändert;
Ground-Slam-Distanz, eigener Widget-Tick und Root-Höhenmodul werden vor dem
Paketbau byteweise gegen .37 verglichen.

Kein Live-Spieltest oder Animations-Render hier möglich. Die vollständige
native Ausrichtung ist eine bewusste Gameplay-Änderung und braucht Nutzer-QA.
Wenn Zittern mit geschlossenen Gates bleibt, ist ein gemessener Pose-/Writer-
Verlauf nötig. Paket-CRC, Loader-Root, beide Versionsfelder und alle Dateien
werden vor Ausgabe geprüft; Hashes: `PACKAGE_SHA256_0.3.9.38.json`.
