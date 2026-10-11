# 0.3.9.23 – lokale Validierung

## Ergebnis

377 Tests ausgeführt: 373 erfolgreich, 4 bereits vorhandene übersprungen.
Basis .22: 354 Tests, davon 350 erfolgreich und dieselben 4 übersprungen.
Python-Syntax und SDKMOD-Archivintegrität geprüft. Keine Windows-Spielausführung.

## Neue Regressionen

23 zusätzliche Tests prüfen die refaktorierten Pfade:

- Hold-Release und Toggle-Release folgen dem nativen Zustand.
- Der alte State 2 wird weder im Press- noch im Release-Callback bestätigt.
- Kurzer Toggle-Tap darf nach physischem Release durch Native State bestätigt werden.
- Native Unterbrechung/Wiederaufnahme: gehaltene Taste, freie Taste, Release in der
  Lücke, neue normale Waffe und Sniper, kein erzwungenes Resume.
- FOV-Reversal derselben Waffe und Kalibrierung einer neuen Waffe aus dem
  ursprünglichen Hip-FOV statt dem noch sichtbaren ADS-FOV.
- Ein Scope-Rückweg wartet auf native Kamera-Blend-Beendigung, keinen Timer.
- Das Ende der FOV-Ausblendung verändert die physische Halteabsicht nicht.
- State 0/3 mit aktiven oder FF-Latches wird nicht als ADS bestätigt.
- FPS-Sniper, Kontextwechsel, Laufzeitbesitzerwechsel, native ZoomedOut-
  Benachrichtigung vor Block-Entscheidung und reentrante Kamera-Benachrichtigung.
- Ein Equip-Paar bei Native State 0 publiziert keine Pose/Reticle und ruft keinen
  Sight-Recovery-Helper auf.
- Schreibverweigerndes ZoomState-Testobjekt auf allen neuen Ablaufpfaden; zusätzlich
  AST-Prüfung des gesamten Mod-Pakets auf direkte und aliased Struct-Zuweisungen.
- Echter Loader im separaten Prozess: Import, reale Keybind-/Zoom-Callbacks,
  State-Einstieg, Waffenwechsel, Toggle-Release, lazy Reticle-Import und Cleanup.
- Hybrid-Scope-Ein-/Ausstieg bei aktivem Toggle-ADS und freier ADS-Taste.

Die bisherigen Tests folgen den neuen Modulgrenzen. Die zwei historischen
Latch-Gate-Prüfungen prüfen jetzt tatsächliche Reticle-/Gap-Readiness; die
native-Exit-Cleanup-Prüfung setzt keine physische Release-Entscheidung voraus.
Die gelöschten Writer-APIs sind keine Kompatibilitäts-Stubs.

## Paket

`dist/BL4ThirdPersonPOC.sdkmod`: 104 Dateien, genau ein Root `BL4ThirdPersonPOC`.
Jeder Payload wurde mit seiner Quelldatei verglichen; alle Python-Dateien parsen.
SHA-256: `f69298de41dbf67efa3904cfbeafd47e7de500b5d92053259bf638a15f000d95`.

Gegen .22 geprüft: 10 geänderte Paketdateien/Metadaten, 2 neue Module.
Alle übrigen Paketdateien sind bytegleich. Änderungsliste:

- Neu: `ads_control.py`, `ads_handoff.py`.
- Geändert: `__init__.py`, `pyproject.toml`, `camera_events.py`, `camera_math.py`,
  `ads_events.py`, `hybrid_ads.py`, `native_lifecycle.py`, `ads_zoom_modifiers.py`,
  `ads_qa_snapshot.py`, `ui_and_commands.py`.

Die validierten nativen Patch-Module und der Reticle-Publisher sind unverändert.
Keine neue Probe oder Diagnose-Hook wird mitinstalliert. Der Snapshot erfolgt
nur auf F10. Der laufende ADS-Abgleich verwendet bestehende Kamera-Updates und
Collector-Hooks; es gibt keine RAM-Suche und keinen Polling-Timer.

## Grenzen

SDK-Stubs beweisen weder native Ereignisreihenfolge noch HUD-Zeichnung, Windows-
Calling-Conventions oder FPS im Spiel. Die neuen Folgen reproduzieren die
beobachtete Reihenfolge als gezielte Szenarien, keinen vollständigen Live-Replay.
Der vollständige Ursprung aller Hold-ADS-Probleme bleibt offen. Die Mod folgt
nun der nativen Entscheidung; eine nativ bestehenbleibende ADS-Aktivität wird
nicht durch Mod-Schreibzugriffe umgedeutet. Spiel-Testplan liegt bei.
