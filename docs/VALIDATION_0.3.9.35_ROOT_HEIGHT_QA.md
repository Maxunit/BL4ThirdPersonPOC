# 0.3.9.35 – lokale Validierung

549 Tests: 545 erfolgreich, vier optionale Keystone-/Capstone-Tests übersprungen.
Befehl: `python -m unittest discover -s tests -p 'test_*.py'`.
Vollständige Ausgabe: `TEST_OUTPUT_0.3.9.35.txt`.

15 neue Tests führen die tatsächlichen Offset-, Mantle-, Motion- und Root-
Funktionen aus: Start auf abgesenkter Fläche, 600 Updates ohne Wegadaption,
Motion aus/an, reiner Root-Versatz ohne doppelte Motion-Reaktion, zusätzliche
Landekompression, Rückkehr ohne Restoffset, Pitch/Roll-Projektion in Welt-Z
bis ±90°, ein geteiltes Actor-/Mesh-/Spine-Sample pro Update, Air-/Crouch-Release,
ADS/Fahrzeug/Shop/Slide/Leiter/Lifecycle/UI/FFYL-/Custom-Gates, Mantle-Sperre,
fehlender Root, ungültige/nichtfinite Felder, abgelaufene WeakPointer,
SDK-Reentry mit geänderter Runtime, unscoped/fremde Setter und Abschalten.

Drei reduzierte Messreihen aus Bens .34-Aufnahmen werden mit allen 1.800 Zeilen
gegen die echten Funktionen abgespielt. Der Stand auf dem Geländer behält rund
−44,13 Einheiten Korrektur; Bodenstand und Rückkehr enden bei exakt null.
Fixture und ZIP-Provenienz: `tests/fixtures/root_height_0_3_9_34.json`.
Das ist eine Berechnung mit beobachteten SDK-Werten, keine nachgebildete
Engine-Kollisions-/Animations-/Render-Schleife und kein Live-Spieltest.

Ein separater Prozess importiert den tatsächlichen Loader, führt den neuen
Console-Parser aus, verwendet den realen scoped Kamera-Setter und prüft den
identischen Menü-Schalter, Scope-Ende einschließlich Fehler beim Start des
Shoulder-Scope sowie echten Mod-Shutdown. Der Menü-Dispatch-Test prüft den
Toggle-Klick. Die SDK-UI kann hier nicht im Spiel gerendert werden.

Ausgewählte Kamera-Aufrufzahlen mit vorhandener Motion: .34 und .35 zählen
je sieben erfasste UFunctions pro gewöhnlichem Stand-Update; bei .35 spart die
Sample-Teilung zwei Calls ein, Root und FFYL-Guard fügen je einen hinzu. Ohne
Motion steigt dieser Ausschnitt von vier auf sechs Calls. Bei aktiver Absenkung
kommt ein Offset-Setter hinzu. Zusätzlich benötigt die .35 Runtime-, Floor-,
Property- und Weak-Prüfungen. Diese Zahlen erfassen ausdrücklich nicht alle
SDK-/Python-Kosten und belegen weder gleiche Laufzeit noch einen FPS-Gewinn.
Mit Höhenkorrektur aus entsprechen die ausgewählten Calls wieder .34.
Daten und reproduzierbarer Befehl: `CAMERA_CALL_COUNTS_0.3.9.35.json` und
`python tests/root_height_cost_scenario.py <.34-Quellordner>`.

Der vorhandene Omni-Stand-Zähltest über 600 Updates ist zu .34 identisch.
Er enthält den Kamera-Updater nicht; siehe `OMNI_CALL_COUNTS_0.3.9.35.json`.
Alle bisherigen ADS-, Fahrzeug-, Omni- und Native-Tests bestehen weiter,
einschließlich der ausgeführten GNU-/x64-Free-Look-Prüfung.

112 Produktionsdateien: sieben geändert, eine neue Datei, 104 bytegleich zu .34.
Alle Omni-/nativen Produktionsmodule bleiben bytegleich. Bestehendes Build-Gate,
Patch-Fingerprints und native Wiederherstellungen sind unverändert.
Paket-CRC, genau ein Loader-Root, beide Metadatenversionen und jede Archivdatei
gegen den Quellstand geprüft. Produktionshashes: `PACKAGE_SHA256_0.3.9.35.json`.
