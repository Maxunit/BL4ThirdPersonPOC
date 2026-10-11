# 0.3.9.34 – lokale Validierung

534 Tests: 530 erfolgreich, vier optionale Keystone-/Capstone-Tests übersprungen.
Befehl: `python3 -m unittest discover -s tests -p 'test_*.py'`.
Ausgabe: `TEST_OUTPUT_0.3.9.34.txt`.

17 neue Tests prüfen die tatsächlichen Diagnoseabfragen und relative Höhenwerte,
simuliertes Body-Absinken gegenüber Kamera-Anheben, 600-Update-Grenze,
Abmeldung/JSON, Startverweigerung bei Thread/UI/fehlendem Spine, Labels,
Profiler-Sperre, fremden F10-Aufruf, Weak-/Runtime-/Komponentenwechsel,
Verwerfen durch SDK-Reentry geänderter Teilaufnahmen, fehlende optionale Felder,
Nicht-finite-Kerndaten, partielle Registrierung und wiederholbare Abmeldung,
fehlgeschlagene Dateiausgabe und rein lesende Ground-Slam-Diagnosekopien.

Separater Prozess importiert den tatsächlichen Loader: neuer Console-Parser,
F10-Bind und echter `runtime_updates.Owner.filtered`-Pfad. Fremdes Widget führt
keine Aufnahme aus; 600 Aufrufe des eigenen Widgets speichern und entfernen
die Route. Vorheriges F10-/Profiler-/ADS-Verhalten besteht in der Gesamtserie.

Stand-Zähltest über 600 Updates ohne Diagnose: erfasste SDK-Zahlen identisch zu .33.
Das belegt keine Spiel-FPS und sagt nichts über Diagnosekosten während der Aufnahme.

111 Produktionsdateien gegenüber .33: drei geändert (Loader, Metadaten,
Shutdown-Koordination), ein neuer Sammler, 107 bytegleich. Alle Omni-, Kamera-
Verhaltens- und Native-Module sind unverändert. Die .33-Tests einschließlich
der ausgeführten GNU-/x64-Free-Look-Präfix-Prüfung bestehen weiterhin.

Paket: CRC, Versionsangaben, Loader-Root und exakte Archiv-/Quellübereinstimmung
geprüft. Hashes/Provenienz: `PACKAGE_SHA256_0.3.9.34.json`.
SDK-Stubs ersetzen nicht den Live-Spieltest; nicht jedes optionale Floor-/Capsule-
Feld muss im echten Spiel verfügbar sein. Fehlende Felder werden transparent
gemeldet. Kein Fix für den noch ungeklärten Kamerahöhenbefund enthalten.
