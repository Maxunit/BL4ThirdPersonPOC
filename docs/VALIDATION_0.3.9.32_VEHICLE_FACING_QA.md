# 0.3.9.32 – lokale Validierung

493 Tests: 489 erfolgreich, vier übersprungen wegen fehlender optionaler
Keystone-/Capstone-Pakete. Befehl:
`python3 -m unittest discover -s tests -p 'test_*.py'`.
Ausgabe: `TEST_OUTPUT_0.3.9.32.txt`.

14 neue Tests üben die echten Publisher und die bestehende Exit-Aufnahme aus:

- Summon verwendet den aktuellen Actor-Yaw und liest den Input-Getter nicht.
- Idle-/Post-exit-Drehungen ersetzen den alten Zielwinkel; Winkel werden gewrappt.
- NaN/Inf bei Summon stoppt vor Veröffentlichung, mit bereits geschlossenem Gate.
- Pause, fehlende aktive Session, Kamerablend, fremdes ViewTarget, Luft und
  gesperrter Normal-Kontext lesen keinen Actor-Yaw und öffnen das Gate nicht.
- Abgelaufene Figur oder fremder Controller schlagen vor dem neuen Getter fehl.
- Alte geschlossene Sitz-/Summon-Tickets werden weiter gelöscht.
- W/S/A/D-Richtungen mit 0, 20, 149, 150, 151 und 600 cm/s: Ausstiegsziel bleibt
  Fahrzeug-Yaw. Kurze Drehungen werden auch vor dem Stillstand übernommen.
- Nicht endliche Fahrzeugrotation veröffentlicht keinen neuen Zielwinkel.
- Fremder Fahrer wird vor der Fahrzeugrotationsabfrage abgelehnt.
- Native-Report liest den tatsächlich eingesetzten Winkel, Kamerawinkel,
  Veröffentlichungsindex und das Alter aus dem bestehenden letzten Datensatz.
- Defekte/fremde/nicht endliche Datensätze oder ungültige Anzahlen betreffen
  ausschließlich die Diagnose.
- Echter `ExitFacing.frame` übernimmt den Native-Winkel in den Report, bevor der
  bestehende Sitzabschluss die Record-Zähler löscht.

Die fünf bisherigen Exit-Facing-Tests wurden auf das bestätigte Verhalten
Fahrzeugausrichtung bei jedem Tempo umgestellt. Die übrige .31-Serie inklusive
Lichtschützen-, Handoff-, ADS-/Hybrid-Reticle-, Callback-Scope-, Bind-, Restore-
und Profiler-Tests besteht weiter. Die Tests laden auch den gebauten `.sdkmod`.

108 Produktionsdateien, davon vier geändert: Loader, Versionsmetadaten,
`omni/vehicle_exit.py` und `omni/vehicle_summon.py`. Die restlichen 104 Dateien
sind bytegleich mit dem gepinnten Repo-.31-Commit.

In beiden Fahrzeugmodulen sind sämtliche Modulkonstanten/Native-Templates
unverändert; nur die aufgegebene `MIN_TRAVEL_SPEED`-Konstante entfällt.
27 Guard-/Layout-/Installer-/Restore-Funktionen sind AST-gleich mit .31.
Einzelheiten und Quell-/Build-Hashes: `PACKAGE_SHA256_0.3.9.32.json`.

SDKmod: 108 Dateien, Quellen bytegleich zum Archiv, CRC und Versionsangaben
geprüft. Python-Caches sind ausgeschlossen. Linux/SDK-Ersatzobjekte ersetzen
keinen Spieltest und beweisen keine FPS-Wirkung oder endgültige native Richtung
im Windows-Livebetrieb. Es ist ein gezielter QA-Build.
