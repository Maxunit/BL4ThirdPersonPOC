# 0.3.9.40 – lokale Validierung

`python -m unittest discover -s tests -p 'test_*.py' -v`:
592 Tests, 587 bestanden, fünf optionale übersprungen.
Ausgabe: `TEST_OUTPUT_0.3.9.40.txt`.

Neun neue Regressionstests behandeln nur die eigene Exit-Root-Zuständigkeit:
83 Special-/Publish-Durchläufe mit Gates (1,1,1,0,0,0), kein Aktivieren von
IdleUpdate/Aim und kein Actor-Setter; Root-Validierung einmal beim Erwerb;
Root-Freigabe in neuer Luftphase auch nach einem vorherigen Exit; kein Root-Hold
in Luft-/TPS-Blend ohne gesehenen Exit; Halten durch 35 eigene Rückkehrupdates;
Disarm vor normaler Veröffentlichung; wiederholter direkter Publish akzeptiert
nur die eigene Root-Zuständigkeit; fehlender/geänderter Root-Guard publiziert
keinen Ersatz; Freigabe bei anderen Sonderzuständen; vollständiger Shutdown.
Der echte `GameplaySession.frame` prüft Luft → Exit → eigenen TPS-Blend →
normales Resume und zeigt, dass die regulären Root/Idle-Gates anschließend
von der regulären Pipeline übernommen werden können.

Die vorhandenen .39-Heading-Tests bestehen weiter; ihr Exit-Erwartungswert ist
jetzt (1,1,1,0,0,0), der Luft-Erwartungswert bleibt (1,1,0,0,0,0). Die ältere .36-
Frame-Fixture enthält nun auch minimale installierte Root-Guard-Stubs; ihre
Getter-/Aim-/Resume-Assertions bleiben. Sämtliche bestehenden Free-Look-, ADS-,
Fahrzeug-, Root-Höhen-, Distanz- und Cleanup-Tests sowie vorhandene ausführbare
x64-Präfixprüfungen bestehen. Die Native-IdleRoot-Templates werden nicht geändert;
keine Behauptung einer neuen Live-Ausführung oder vollständigen Render-Prüfung.

Die standalone Exit-Probe besteht 16 SDK-/Native-Stub-Tests, einschließlich
korrekter Kennzeichnung des absichtlich gehaltenen .40-Root-Gates gegenüber
unerwartetem IdleUpdate/Aim. Core-Mod und Diagnosescript werden getrennt geprüft.

Produktions-Bytevergleich gegen .39 erwartet genau vier geänderte Dateien:
`__init__.py`, `pyproject.toml`, `omni/session.py`, `omni/slam.py`. Alle nativen
Templates/Fingerprints, Distanz (150 cm), Kamera-Root-Höhe und Update-Zeitquelle
sind unverändert. `.sdkmod`: 113 Dateien, ein Loader-Root, CRC, Quellgleichheit
und drei Versionsfelder geprüft. Hashes: `PACKAGE_SHA256_0.3.9.40.json`.
Dev-ZIP: nur getrackte Dateien ohne Caches/Git/dist, CRC und jede Datei vor
Ausgabe gegen ihre Quelle geprüft.

Noch ausstehend: Nutzer-QA für vollständige Slam-Pose und ruhige Root beim Exit.
Sequential SDK-/Bone-Beobachtungen und private Gate-Publikation beweisen keine
atomare native Animationsevaluation; die Basis-Pose darf weiterhin eigene
Root-Bewegung enthalten. Weitere Fixes benötigen gemessene verbleibende Fehler.
