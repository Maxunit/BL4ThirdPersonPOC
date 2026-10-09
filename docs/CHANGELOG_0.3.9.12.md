# BL4ThirdPersonPOC 0.3.9.12 – Beam-Tiefe, Throwables mit Omni, Sprint-Feuer-Absicherung

Basis ist 0.3.9.11. **Noch nicht im Spiel getestet**, siehe `TESTPLAN_0.3.9.12.md`.

## Beam: Abfrage startet auf Figurentiefe
- **Ursache:** Der Beam-Eingriff `native_beam_origin.py` (Umweg am Funktionsbeginn `0xA640F0`) schrieb bisher die Kamera-Cache-Position (`Manager+0x1910`) als Abfragestart in `Receiver+0x388`. Die Beam-Abfrage (Sweep, Radius 20) lief deshalb von der Kamera aus. Wandkante neben der Kamera und Gegner im Rücken waren Treffer, genau wie bei den Kugeln vor 0.3.9.9.
- **Fix:** Der Stub verschiebt den Start vor dem Schreiben entlang der Kamera-Blickrichtung. Das ist dieselbe Regel wie beim Ziel-Trace:
  - `d = (cos p · cos y, cos p · sin y, sin p)` aus `CameraCachePrivate.POV.Rotation`
  - `Tiefe = (Pawn − Kamera) · d + Rand`
  - `Start = Kamera + d · Tiefe`, nur wenn `0 < Tiefe < 1500`
  - sonst wie bisher die Kameraposition
- **Gemeinsamer Steuerblock mit dem Ziel-Trace:**
  - Pawn-Position und An/Aus kommen aus demselben Block, `bl4tps_aim off` schaltet beide Korrekturen ab.
  - Der Block existiert einmal pro Spielprozess und wird nie freigegeben.
- **Eigener Beam-Rand:** `bl4tps_aim beam_margin <cm>`, Standard 70 cm wie bei den Kugeln.
  - Bei den Kugeln bestimmt der Trace nur den Zielpunkt, die Kugel fliegt weiter von der Mündung und trifft Deckung vor der Waffe.
  - Beim Beam entscheidet die verschobene Abfrage selbst über die Treffer. Was auf dem Fadenkreuz-Strahl näher als Figurentiefe + Rand liegt, trifft der Beam nicht.
  - Das löst die Wandkante. Es heißt aber auch: Steht man näher als etwa 70 cm vor einer Wand oder dicht an Deckung, kann der Beam hindurchgehen.
  - Ein kleinerer Wert (z. B. 30) hält solche Deckung im Spiel, behebt die Wandkante aber eventuell nicht ganz. Der Spieltest entscheidet den Standard.
- **Rotation-Offset:**
  - Er wird nicht hart eingetragen, sondern per Reflection bestimmt (`CameraCachePrivate` → `POV` → `Rotation`).
  - Geprüft wird beim Einschalten:
    - Der Location-Offset muss `0x1910` sein, wie gemessen.
    - `Rotator` hat Double-Felder Pitch@0, Yaw@8.
    - Die Bytes im Speicher müssen dem live gelesenen `POV` entsprechen.
  - Schlägt eine Prüfung fehl, läuft der Beam ohne Verschiebung weiter wie bisher (`BEAM_DEPTH enabled=False reason=…`).
- **Unverändert:**
  - alle bisherigen Prüfungen (Build, SHA-256 über `0xF00` Bytes, Anker, Receiver-Vtable, Waffe, Modus 5, TPS-Definition);
  - die 64 Datensätze;
  - der nachgespielte Funktionsanfang.
- **Register:** Der Stub nutzt zusätzlich `xmm0`/`xmm1` (gesichert und zurückgeschrieben) und kurz den x87-Stack. Der ist beim Einstieg leer und beim Verlassen wieder leer.
- **Kollisions-Helfer `native_beam_collision`:** Er greift nur bei Abfragen, die an der Kamera starten. Bei verschobenem Start behält er das Originalergebnis bei. Sein Zweck (Kamera-Präfix) entfällt dann.
- **Status:**
  - `bl4tps_aim status` zeigt unter `beam` die Zähler `applied`, `skipped`, `off`, `last_depth`, `last_camera` und `last_origin`.
  - Beim Einschalten erscheint `[BL4ThirdPersonPOC.BeamOrigin] BEAM_DEPTH enabled=… reason=… rotation=…`. `reason=armed` heißt: Der Stub verschiebt, solange `bl4tps_aim` aktiv ist.

## Throwables: Körper dreht mit Omni in Wurfrichtung
- **Ursache:** Omni dreht den Körper nur bei Kampf-Signalen zur Kamera (ADS, Feuer, Zoom, Feuer-Animation). Ein Wurf war keines.
- **Neues Kampf-Signal `throw_hold`** (`omni/throw_handoff.py`):
  - **Start:** durch die Ordnance-Taste (`Action_Gadget`, neue optionale Rolle) oder durch Feuer im Throwable-Kontext. Diesen erkennt die Mod daran, dass in den aktuellen Mappings `Action_Zoom` fehlt.
  - **Dauer:** solange die Taste gehalten ist und solange die mit dem Wurf gestartete Montage auf der 3rd-Person-Animation läuft (`GetCurrentActiveMontage`, `Montage_IsPlaying`).
  - **Welche Montage zählt:** eine, die nach dem Drücken erscheint, oder eine, die beim Drücken gerade erst begonnen hat (Position ≤ 0,15 s, `Montage_GetPosition`). Eine Montage, die schon länger lief (z. B. Nachladen), zählt nicht.
  - Höchstens eine direkt anschließende, frisch gestartete Montage wird mitverfolgt.
  - **Ohne Timer:** Das Signal endet mit der Montage. Startet keine neue Montage, endet es eine Abfrage nach dem Loslassen.
- **Konsole:**
  - für die ersten 8 Würfe: `THROW_HOLD source=… montage=…` bzw. `THROW_NO_MONTAGE`;
  - im Omni-Report: `throw_episodes`.
- **Fehlerverhalten:** Fehlen die Montage-Funktionen, meldet die Mod einmal `THROW_MONTAGE_UNAVAILABLE`. Der Wurf hält den Körper dann nur, solange die Taste gedrückt ist, und Omni läuft weiter.
- **Unbrauchbare `Action_Gadget`-Mappings** (fremde Aktionsklasse, fehlende Taste, Chord/Combo-Trigger) werden übersprungen, nicht abgelehnt. Bewegung, Feuer und Zoom bleiben streng.

## Sprint-Feuer-Brücke (Befunde B1/B2 aus der Sichtung)
- **B1: Lesefehler stoppen Omni nicht mehr.**
  - Strukturabweichungen beim nativen Lesen schalten nur die Brücke für diesen Druck ab. Betroffen sind:
    - Waffe nicht genau einmal im Weapon-User
    - Grenzen
    - Bindung während des Lesens geändert
  - Die Mod meldet dann einmal je Grund `SPRINT_FIRE_NATIVE_UNAVAILABLE`, im Report steht `sprint_fire_read_failures`.
  - Abweichender Maschinencode wird nicht erneut versucht.
  - Gelesen wird nur noch die Waffe der laufenden Brücke im Zustand Active/Using. Waffenwechsel und Ziehen beenden die Brücke vorher sauber.
  - Andere Ausnahmetypen bleiben sichtbar, denn sie sind echte Fehler.
- **B2: Ausgang ohne Feuerauftrag.**
  - Erzeugt ein Druck weder Auftrag noch Aktivität, gibt die Brücke eine Abfrage nach dem Loslassen frei (`NO_NATIVE_REQUEST`). Typischer Fall: Gamepad-Trigger nur leicht angedrückt.
  - Gezählt werden Abfragen, keine Zeit.
  - Gültige Schüsse zeigen den Auftrag sofort (19/19 Aufzeichnungen) und nehmen diesen Weg nie.
  - Konsolenzeile: `SPRINT_FIRE_NOT_ADMITTED reason=…`.

- **Bekannt, nicht neu:** Bleibt ein gesehener Feuerauftrag dauerhaft offen, hält die Brücke weiter bis zu Zustandswechsel oder Abbruch. Das trat in keiner Aufzeichnung auf.

## Sonstiges
- Der GitHub-Workflow baut jetzt vor den Tests. Damit läuft der Paket-Smoke-Test auch dort.
- In der README steht der Testplan-Verweis.

## Prüfung
- 212 Python-Tests.
- Neu: `test_fixes_0_3_9_12.py` (29) und `test_beam_depth_0_3_9_12.py` (15).
- Ein unabhängiges Review lief über alle Änderungen. Umgesetzt daraus:
  - eigener Beam-Rand
  - Montage, die schon im Druck-Frame startet
  - Montage-Kette begrenzt
  - unbrauchbare Ordnance-Mappings werden übersprungen
- **Beam-Stub auf Linux x64 in einem nachgebauten Speicherabbild ausgeführt.** Geprüft:
  - gerade und schräge Blickrichtung
  - aus, hinter der Kamera, jenseits des Maximums, NaN
  - fehlender Steuerblock
  - fremde Receiver, Modus, First-Person
  - Datensatz-Limit
  - Alle Argument- und Scratch-Register, `xmm0`–`xmm2` und der leere x87-Stack werden bei jedem Lauf geprüft.
- Mit ausgeschalteter Tiefe verhält sich der neue Stub byte-genau wie der alte: gleiche Schreibzugriffe, gleiche Datensätze.
- Die Assembler-Quelle liegt in `docs/beam_origin_stub_source.py`.
