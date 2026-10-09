# BL4ThirdPersonPOC 0.3.9.0 – Omni-Integration

Basis: 0.3.8.17 plus Omni-Laborpaket „Weapon Fire State Diagnostic“ (08.10.2026).
Die Gameplay-Logik und alle nativen Templates bleiben unverändert. Der V3-Audit-Test bestätigt das für die geprüften Worker per AST-Hash.
**Noch nicht im Spiel getestet**, siehe `TESTPLAN_0.3.9.0.md`.

## 1. Omni als Teil der Mod
- Das Laborpaket `bl4_omnidirectional` liegt jetzt als Subpaket `BL4ThirdPersonPOC/omni/` in der Mod. `pyexec player_omnidirectional_gameplay.py` wird nicht mehr gebraucht.
- Die Mod wird explizit übergeben. Omni sucht sie nicht mehr über `sys.modules`.
- Omni überschreibt `_on_disable_impl` nicht mehr. Stattdessen gibt es eine eigene Stufe `omni_movement` ganz am Anfang von `mod_shutdown`.
  - Diese Stufe läuft, bevor sich Kamera, Flags oder Updater ändern.
  - Schlägt sie fehl, bleiben Kameragruppe und `runtime_updates` erhalten (fail closed).
- Reports landen unter `sdk_mods/settings/BL4ThirdPersonPOC_reports/`. In einer `.sdkmod` (Zip) wäre der Pfad neben dem Modul nicht beschreibbar. Es bleiben höchstens 40 Dateien erhalten.
- Pinning-Lücke geschlossen: Der Stub von `NativeTrace` referenziert `slide_control` und `slide_buffer`. Beide hängen jetzt am gepinnten `control`, genauso wie `crouch_control`. Die Template-Klasse selbst ist unverändert.
- Kaltstart: Ein `ClientRestart` vor der Game-Thread-Bindung ist kein Fehler mehr, solange noch keine Gameplay-Session existiert. Vorher hätte der automatische Start beim Laden ins Spiel `LIFECYCLE_FAILED` ausgelöst.
- Der Supervisor braucht beim Start kein lebendes Widget mehr, nur den gestarteten Update-Producer. Geroutete Callbacks laufen ohnehin erst, wenn das Widget tickt.

## 2. Schalter, Menü, Konsole
- Neue versteckte Optionen:
  - `omni_movement_experimental` (Standard aus)
  - `omni_movement_diagnostics` (Standard aus)
- Im F7-Menü unter CAMERA MODES gibt es den Abschnitt „MOVEMENT (EXPERIMENTAL)“ mit TOGGLE.
  - Die Anzeige zeigt `ON`, `OFF` oder `ON - STOPPED (see console)`.
  - Reset der Seite und „Defaults“ schalten das Feature aus.
- Die Option wird erst gespeichert, wenn Start bzw. Stopp wirklich geklappt hat.
- Konsolenbefehl `bl4tps_omni` mit `on | off | status | report | diag on|off`:
  - `report` schreibt einen Snapshot, ohne zu stoppen.
  - `diag` startet eine laufende Session neu.
- Ist die Option an, startet das Feature automatisch mit der Mod und wartet auf normales On-Foot-TPS.

## 3. Produktionsmodus (Diagnose aus)
- Phasen- und Statusmeldungen (FOLLOW_ACTIVE, COMBAT_AIM, WAITING_* …) gehen nur noch an `dev_warning`. Fehler bleiben `error`, ein Fehlerstopp meldet `STOPPED_ON_ERROR`.
- Pose-Diagnose und Weapon-Fire-Diagnose laufen nur mit `diag on`.
- JSON-Reports gibt es nur noch bei Diagnose, bei Fehlern oder bei unvollständigem Cleanup.
- Eingaben:
  - Pro Callback wird der Tastenzustand nur einmal ausgewertet (vorher 4–6 Mal).
  - Der vollständige Mapping-Scan läuft nur noch bei geänderter Mapping-Anzahl, nach dem Schließen eines Menüs oder alle 30 Updates. Vorher lief er in jedem Frame.
  - Die Abfrage in Zustände „Owner gewechselt“ oder „Mapping unvollständig“ greift weiterhin sofort.
- Kein Rotations-Snapback mehr: Beim Stopp wurde der Körper bisher auf die Rotation vom Follow-Start zurückgesetzt. Jetzt übernimmt das Spiel die Rotation direkt.
- Metadaten zur Eingabe werden nur noch bei einem Revisionswechsel erzeugt.

## 4. ADS/Interaktion folgen den Spielaktionen
- `input_bindings.py` ist der gemeinsame Mapping-Leser für Omni und Hauptmod.
- `action_keys.py` setzt die versteckten Keybinds auf die im Spiel konfigurierten Tasten.
  - ADS folgt `Action_Zoom`, getrennt für Maus/Tastatur und Gamepad.
  - Trigger-Achsen werden auf den digitalen Trigger abgebildet.
  - Ohne passende Belegung bleibt die bisherige Taste.
- Die Interaktion bleibt vorerst auf E/Viereck. Der Name der Use-Aktion ist noch nicht im Spiel bestätigt, geraten wird nicht. `bl4tps_actions` listet alle Aktionen mit ihren Tasten.
- Gearbeitet wird auf dem eigenen Widget-Tick. In offenen Menüs passiert nichts, und Fehler werden je Fehlertext nur einmal gemeldet.

## 5. Zentrales Build-Gate
- `build_gate.py` enthält die Build-Identität (PE TimeDateStamp/SizeOfImage/Machine), die Liste geprüfter Builds und einen Steam/Epic-Hinweis.
- Bei unbekanntem Build gilt:
  - Es werden keine Hooks und keine Patches installiert.
  - Alle Keybinds und Befehle sind aus, nur `bl4tps_build` bleibt aktiv.
  - Die Konsole zeigt eine kompakte Fehlermeldung `INACTIVE_UNREVIEWED_BUILD`.
- Die verstreuten Build-Literale in 14 Dateien zeigen jetzt auf `REVIEWED_BUILD`. Die zwei auditierten V3-Dateien behalten ihr Literal, ein Test prüft die Übereinstimmung.

## Tests
- 83 Python-Tests, darunter die 48 aus dem Lab. Der V3-Audit-Test ist jetzt Python-versionsfest (`ast.dump(show_empty=True)`).
- Neu ist ein Smoke-Test, der die echte `__init__.py` unter SDK-Stubs lädt, auch direkt aus der gebauten `.sdkmod`. Er prüft Enable, Toggle, Report und Disable einschließlich Hook-Bilanz.
- Die Idle-Scope-Template-Validierung läuft weiterhin mit 96/96.
