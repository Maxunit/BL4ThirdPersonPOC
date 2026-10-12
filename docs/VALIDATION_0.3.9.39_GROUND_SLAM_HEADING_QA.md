# 0.3.9.39 – lokale Validierung

`python -m unittest discover -s tests -p 'test_*.py' -v`:
583 Tests, 578 bestanden, fünf optionale übersprungen.
Ausgabe: `TEST_OUTPUT_0.3.9.39.txt`.

Neun neue Regressionstests prüfen:

- Luft-Slam: 50 echte Special-/Publish-Durchläufe mit Gates
  (Turn, TurnReplace, IdleRoot, IdleUpdate, Aim, CrouchAim) = (1,1,0,0,0,0).
  Alter Slide-Caller wird auf den gemessenen TurnState-Caller umgestellt.
  Keine zwischenzeitliche Aktivierung von Idle-/Aim-Gates, kein Actor-Setter;
  zusätzliches Native-Validate nur beim Erwerb.
- Hold über GroundSlamExit und eigenen TPS-Blend.
- Freigabe bei Combat/ADS/UI/Fahrzeug/Shop/Leiter/Slide/FPS/fremdem Modus
  oder fehlender eigener Input-Zuständigkeit.
- Verwerfung gemischter Pose-Gates und eines fehlenden nativen Guards.
- Fehlgeschlagene native Owner-Validierung publiziert keinen Ersatz.
- Normale Omni-Kontrollen ohne Slam-Eigentum werden nicht verändert.
- Echter `GameplaySession.frame` durch Special-/Exit-Pfad und normalen Resume:
  der Hold wird nach der alten Pipeline publiziert und beim Ende vor normalem
  Omni-Publish geschlossen. Wiederaufnahme öffnet ihre eigenen Gates korrekt.
- Bestehender Shutdown schließt beide Heading-Gates vor nativer Bereinigung
  und beendet die Report-Zuständigkeit.

Der ältere echte Frame-Test aus .36 benötigt jetzt vollständige minimale
Controller-/Native-Guard-Stubs: vorher gab es in der Fixture keinen Controller
und keinen installierten Guard. Seine Pose-/Getter-/Resume-Assertions bleiben.

Zusätzlich laufen die standalone Probenprüfungen: Facing sechs Tests,
Rotation-Recorder elf Tests; SDK und native Reads sind dabei gestubbt.
Die üblichen ADS-, Fahrzeug-, Root-, Distanz-, Free-Look- und Shutdown-Tests
sowie die vorhandenen ausführbaren x64-Präfixprüfungen bestehen.
Diese Prüfungen belegen Steuerzustände, Grenzen und Bereinigung. Sie beweisen
weder die live angewendete Körperrichtung noch gerenderte Animationsruhe.

Bytevergleich gegen .38 zeigt genau vier veränderte Produktionsdateien:
`__init__.py` und `pyproject.toml` (Version), `omni/session.py`, `omni/slam.py`.
Alle anderen 109 Produktionsdateien sind unverändert, insbesondere native
Templates/Fingerprints, Ground-Slam-Distanz (150 cm), Root-Höhe und Widget-
Zeitquelle. Keine zusätzliche Update-Subscription oder native Installation.
Der gewöhnliche Omni-Pfad führt keine neuen SDK-Abfragen für diesen Hold aus.

Das gebaute `.sdkmod` enthält 113 Dateien unter genau einem Loader-Root.
CRC, Quellgleichheit, MOD_VERSION und beide Metadatenversionen sind geprüft.
Datei-Hashes stehen in `PACKAGE_SHA256_0.3.9.39.json`. Das Dev-ZIP wird aus
getrackten Dateien gebaut; Caches, Git-Metadaten und dist werden ausgeschlossen
und jede enthaltene Datei vor Ausgabe mit der Quelle verglichen.

Noch ausstehend: Nutzer-QA für die vollständige native Slam-Animation bei
gehaltenem Actor-Yaw, besonders mit Kamera entgegengesetzt zur Figur. Andere
native Drehungspfade als der aufgezeichnete TurnState-Callsite werden von
existing NativeTrace nicht unterdrückt; kein allgemeiner Actor-Freeze.
