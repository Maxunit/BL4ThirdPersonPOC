# 0.3.9.36 – lokale Validierung

`python -m unittest discover -s tests -p 'test_*.py'`: 566 Tests, 561 bestanden,
fünf optionale Tests übersprungen. Ausgabe: `TEST_OUTPUT_0.3.9.36.txt`.

16 neue Slam-Tests prüfen die Produktionsfunktion: Halten/Rückfahrt vor
Kontakt, native Komposition und ältere Snapshots, geschützte fremde Targets
und TPS-Fallback, keine laufenden Traces im Stand/normalen Sprung, Trace-Verlust,
Nullwert/ADS-Handoff, Kalibrierungsfehler, fremde Writer, inaktive Besitzer,
Shutdown-Thread-Gate, tatsächlicher Root-Offset-Setter ohne Kumulation,
sechs aufgezeichnete Slams, echter Omni-Frame vom Front-Fade bis Slam/Exit
und zurück, einmaliger Luft-Getter sowie Freigabe von Jump-Idle und Lean.

Ein separater Prozess importiert den echten Loader und führt seinen scoped
Kamera-Updater, Menüoption und Shutdown aus: 150 cm Zusatz, Root aus/an,
neutraler Abstand vor Kontakt und leere Runtime nach Disable. Der zusätzliche
Publisher-Test schließt beide Aim-Modi während des Slams. Die bestehenden
ausführbaren GNU/x64-Free-Look-Tests prüfen unveränderte Prefixes, Original-
Yaw/Pitch bei geschlossenem Gate und übrige Register-/MXCSR-Erhaltung.

`tests/fixtures/ground_slam_v4_20261011.json` enthält 326 Luft-Updates der sechs
vom Nutzer bestätigten V4-Slams mit Upload-Provenienz und SHA-256. Die getestete
Rückfahrt wird mit 150 cm gegen diese Verläufe abgespielt. Sinkgeschwindigkeit
für diesen Replay ist aus aufgezeichnetem vorhergesagtem Abstand und Zeitdelta
rekonstruiert; daher ist dies eine Berechnungsprüfung mit Messwerten, kein neuer
physikalischer oder Render-Test. Alle sechs Episoden erreichen null vor Exit.

Die .36 selbst wurde hier nicht im Spiel ausgeführt. Animation, Kameragefühl,
Menüdarstellung, Kollisions-/Terrainverhalten und FPS müssen im Spiel geprüft
werden. Die bisherigen ADS-, Fahrzeug-, Omni-, Root- und Shutdown-Tests bestehen.
Paket-CRC, Root-Struktur, beide Metadatenversionen und Archivdateien gegen den
Quellstand werden vor der Ausgabe geprüft; Produktionshashes liegen in
`PACKAGE_SHA256_0.3.9.36.json`.
