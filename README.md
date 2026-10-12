# BL4ThirdPersonPOC 0.3.9.41 Ground Slam Idle Exit QA

Die .40-Aufnahme bestätigt festen Actor, Mesh und Root, aber Aim-Yaw wechselt
im Exit bei jedem Update ungefähr zwischen +177° und -177°. Der aufgezeichnete
IdleTurns-Update enthält eine vorzeichenabhängige Auswahl zweier Dreh-Eingänge.
Sein bestehender Idle-Fallback wählt Eingang 0 und ruft danach weiterhin den
ursprünglichen generischen Update auf. Das wurde zusätzlich nativ mit dem
aufgenommenen Code und synthetischen Receivern/Hilfsfunktionen geprüft.

.41 aktiviert diesen bereits vorhandenen lokal begrenzten Fallback nur beim
Exit und dessen eigener TPS-Rückkehr, zusammen mit Heading-/Root-Hold aus .40.
Aim und CrouchAim bleiben durchgehend freigegeben. Der ältere .37-Exit-Pfad
öffnete Aim zwischenzeitlich erneut; das tut diese QA nicht. In der Luft bleiben
Root-/IdleUpdate-/Aim-Eingriffe aus. Vor normalem Omni-Resume werden eigene
Holds geschlossen; Combat/ADS/UI und andere Sonderzustände behalten Priorität.

Kein neuer nativer Code oder Patch, Hook, Producer, Timer oder gewöhnlicher
Omni-SDK-Getter. Die 150-cm-Distanzfunktion und Root-Höhenkorrektur sind bytegleich
zu .40. Sichtbare Ruhe und vollständige Slam-Pose zusammen benötigen Nutzer-QA.
Der native Replay prüft Auswahl/Dispatch, nicht gerenderte Unreal-Animation.

- [Spieltest](docs/TESTPLAN_0.3.9.41_GROUND_SLAM_IDLE_EXIT_QA.md)
- [Änderungen](docs/CHANGELOG_0.3.9.41_GROUND_SLAM_IDLE_EXIT_QA.md)
- [Validierung](docs/VALIDATION_0.3.9.41_GROUND_SLAM_IDLE_EXIT_QA.md)

## Enthalten: Ground Slam Update aus .37

Die .36 hatte die Distanzberechnung an den Animations-Callback gehängt,
dabei aber das Widget-Argument `InDeltaTime` verwendet. Ohne dieses Argument
blieb das Zeitdelta null und der Zusatzabstand baute sich nicht auf. .37
verwendet wie die bestätigte V4-Probe den eigenen, thread-/widget-gefilterten
Widget-PRE. Der Animations-Callback wendet die Distanz nur an, er berechnet
sie nicht. Bei fehlendem Widget-Zeitargument wird der Abstand zwischen den
eigenen Updates gemessen; ein explizites Delta von null bleibt eine Pause.

Eine zusätzliche Subscription am vorhandenen Widget, kein neuer Producer,
Timer oder nativer Patch. Shutdown entfernt sie vor dem Producer. Fremde
Widgets verändern die Distanz nicht; ein zwischen Widget und Setter gewechselter
Kameramodus bekommt keinen alten Zusatz. F10 loggt den aktuellen Distanzstatus.

- [Spieltest](docs/TESTPLAN_0.3.9.37_GROUND_SLAM_UPDATE_QA.md)
- [Änderungen](docs/CHANGELOG_0.3.9.37_GROUND_SLAM_UPDATE_QA.md)
- [Validierung](docs/VALIDATION_0.3.9.37_GROUND_SLAM_UPDATE_QA.md)

## Enthalten: Oberkörperkorrektur und 150-cm-Option aus .36

Während des aktiven Ground Slams und GroundSlamExit übernimmt die native
Oberkörperanimation: Omni lässt seine Aim-Yaw-/Pitch-Begrenzung aus; im
aktiven Luft-Slam werden auch gewöhnliche Jump-Idle-/Lean-Pose-Eingriffe
freigegeben. Normales freies Umschauen, Sprünge und Richtungssteuerung bleiben
erhalten. Die sichtbare Animationskorrektur benötigt einen Spieltest.

Die bestätigte V4-Distanzfunktion ist integriert: weich herauszoomen, oben
halten, während der Bodenannäherung zurückfahren. Standard **150 cm**;
**CAMERA → Ground Slam Extra Distance**, 0–250 cm, 0 schaltet den Zusatz aus.
Der vorhandene TPS-Ground-Slam-Schalter steuert weiterhin die gesamte Funktion.
Keine PyExec-Probe nötig, keine zusätzlichen Timer oder nativen Patches.
Die beiden Start-Traces kalibrieren am normalen Boden; danach läuft ein Trace
pro aktivem Slam-Update. Im gewöhnlichen Stand und bei normalen Sprüngen gibt
es keine fortlaufenden Boden-Traces.

- [Kurzer Spieltest](docs/TESTPLAN_0.3.9.36_GROUND_SLAM_QA.md)
- [Änderungen](docs/CHANGELOG_0.3.9.36_GROUND_SLAM_QA.md)
- [Lokale Validierung](docs/VALIDATION_0.3.9.36_GROUND_SLAM_QA.md)

## Enthalten: 0.3.9.35 Root Height QA

Gezielte Kamera-QA auf .34 (`1ba29a7`), einschließlich der bestätigten Fahrzeug-
und Omni-Free-Look-Korrekturen aus .32/.33. Die neue Höhenkorrektur folgt einer
Root-Absenkung gegenüber der Mesh-/Bodenreferenz, ohne Figur, Kapsel oder
Animationen zu verändern. Sie bleibt bei anhaltender Absenkung bestehen.
Motion Camera verarbeitet die zusätzliche Oberkörperbewegung separat.

Standard: an. Im Menü unter **CAMERA → Grounded Body Height (QA)** oder mit
`bl4tps_root_height on|off|status` abschaltbar. Funktioniert auch ohne Motion
Camera und ohne Omni. Die erste QA kompensiert normales Gehen/Stehen am Boden;
bei Sprung und Ducken läuft die Korrektur weich aus, besondere Kameramodi
übernehmen ohne diesen Zusatz. Keine neuen Hooks, Timer oder nativen Patches.

- [Kurzer Spieltest](docs/TESTPLAN_0.3.9.35_ROOT_HEIGHT_QA.md)
- [Änderungen und Messgrundlage](docs/CHANGELOG_0.3.9.35_ROOT_HEIGHT_QA.md)
- [Lokale Validierung](docs/VALIDATION_0.3.9.35_ROOT_HEIGHT_QA.md)

Die Höhenaufnahme aus .34 bleibt erhalten: `bl4tps_height arm <label>`, Konsole
schließen und F10. Maximal 600 vorhandene eigene Widget-Updates, danach JSON in
`sdk_mods/settings/BL4ThirdPersonPOC_reports/`. Zusätzlich enthält jede Zeile
`root_height` mit roher Absenkung, Ziel, gefilterter Korrektur und Status.
Die Diagnoseaufnahme selbst schreibt keine Spielwerte. Ohne Vormerkung behält
F10 seine bisherige Funktion. Die .35 enthielt noch keine Slam-Distanzfunktion.

## Enthalten: 0.3.9.33 Omni Free Look QA

Basiert auf .32, lokalem QA-Checkpoint
`d9c63d4` (Repo-.31: `001a62a45d7f9307f1b91088e7b25bfba63d0941`).
Beim freien Omni-Umschauen darf der Oberkörper seitlich mitdrehen: Aim-Eingabe
höchstens ±35°. Körperneigung und Drehung blenden zwischen 60° und 90°
Kameraverdrehung relativ zur Figur weich aus. Ab der Seitenansicht ist dieser
kamerabedingte Aim-Anteil neutral. Gilt im normalen, freien Omni am Boden,
stehend und geduckt. Zielen und Schießen geben die Aim-Pose weiterhin ans Spiel.
Die Fahrzeugkorrektur der .32 ist vollständig enthalten; Ben hat beim ersten
Spieltest mit Lichtschütze und Manta korrekte Ein-/Ausstiegsrichtungen bestätigt.
Ben hat die neue Oberkörperbewegung im ersten .33-Spieltest bestätigt.

- [Änderungen](docs/CHANGELOG_0.3.9.33_OMNI_FREE_LOOK_QA.md)
- [Kurzer Spieltest](docs/TESTPLAN_0.3.9.33_OMNI_FREE_LOOK_QA.md)
- [Lokale Validierung](docs/VALIDATION_0.3.9.33_OMNI_FREE_LOOK_QA.md)
- Vorgänger: [0.3.9.32 Vehicle Facing](docs/CHANGELOG_0.3.9.32_VEHICLE_FACING_QA.md)
- Vorgänger: [0.3.9.31 Summon Seat](docs/CHANGELOG_0.3.9.31_SUMMON_SEAT_QA.md)
- Vorgänger: [0.3.9.30 Exit Facing](docs/CHANGELOG_0.3.9.30_VEHICLE_EXIT_FACING_QA.md),
  [0.3.9.29 Bind & Hitch](docs/CHANGELOG_0.3.9.29_OMNI_BIND_HITCH_QA.md),
  [0.3.9.28 Callback-Scope](docs/CHANGELOG_0.3.9.28_OMNI_CALLBACK_SCOPE_QA.md)
- Zähl-Umgebung: `python tests/omni_idle_cost_scenario.py stand|crouch|move|turn --report`

Installierbar: `dist/BL4ThirdPersonPOC.sdkmod`; gleichwertiger Quellordner:
`BL4ThirdPersonPOC/`. Nur eine Variante installieren. Spiel vollständig beenden
und alte Mod-Dateien sowie ihren PyCache entfernen.

---

# BL4ThirdPersonPOC – Entwicklungsstand

| Pfad | Inhalt |
|---|---|
| `BL4ThirdPersonPOC/` | Die Mod (wird zur `.sdkmod` gepackt) |
| `BL4ThirdPersonPOC/omni/` | Integriertes Omnidirectional Movement (experimentell, Standard aus) |
| `BL4ThirdPersonPOC/build_gate.py` | Zentrale Build-Erkennung (Steam/Epic, geprüfte Builds) |
| `BL4ThirdPersonPOC/input_bindings.py` | Gemeinsamer Leser der Enhanced-Input-Belegung |
| `BL4ThirdPersonPOC/action_keys.py` | ADS-/Interaktions-Keybinds folgen der Spielbelegung |
| `tests/` | Python-Tests mit SDK-Stubs, Smoke-Test der echten Mod |
| `docs/` | Changelog, Testplan, Omni-Labordoku (`docs/omni/`) |
| `tools/build_sdkmod.py` | Baut `dist/BL4ThirdPersonPOC.sdkmod` |

## Bauen und Testen
```
python tools/build_sdkmod.py
cd tests && python -m unittest discover -s . -p "test_*.py"
python docs/omni/run_idle_scope_validation.py   # nur Linux x64
```
Die Tests prüfen die Python-Logik, die Verdrahtung und das Cleanup. Sie ersetzen keinen Spieltest. Aktueller gezielter Nachtest: `docs/TESTPLAN_0.3.9.18.md` (Integration der bestätigten Granaten-Ausrichtung mit Zustandsnachlauf). Die Hybrid-/Omni-Übergabe aus .14, der gehaltene Sniper-Rückweg aus .15, der Objektwurf aus .17 und die längere Granaten-A/B-Variante wurden im Spieltest bestätigt. Weitere offene Tests stehen in `docs/TESTPLAN_0.3.9.13.md` bzw. `docs/TESTPLAN_0.3.9.12.md`; der Reparaturstand steht in `docs/FIX_TRACKER_0.3.9.13.md`.

## Konsolenbefehle (neu in 0.3.9.0)
- `bl4tps_omni [on|off|status|report|diag on|off|hybrid on|off|status]`: `hybrid` schaltet den Hybrid ADS Mode (nur mit Omni) ; Zoom wird im ADS-ZOOM-Menü eingestellt
- `bl4tps_actions [all]`: listet die Spielaktionen, gleicht die Keybinds sofort ab und zeigt den Sync-Zustand
- `bl4tps_build`: zeigt den erkannten Build und das Gate
- `bl4tps_weapon_probe [live]`: misst lesend den nativen Feuer- und Zielpfad der ausgerüsteten Waffe (JSON im Report-Ordner); `live` ruft zusätzlich die beiden Ziel-Getter der Kameraverwaltung einmal auf
- `bl4tps_native_dump <rva> … [--length 0x800]`: liest nur Codefenster für die Offline-Analyse
- `bl4tps_aim [status|on|off|margin <cm>|beam_margin <cm>]`: Ziel-Trace und Beam-Abfrage starten in TPS auf Figurentiefe (Standard an, Rand und Beam-Rand je 70 cm); `status` zeigt unter `beam` die Beam-Zähler

Lokale QA-Prüfung: [VALIDATION_0.3.9.19.md](docs/VALIDATION_0.3.9.19.md).
