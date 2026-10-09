# BL4ThirdPersonPOC 0.3.9.9 – Ziel-Trace startet auf Figurentiefe

Basis ist 0.3.9.8. Ersetzt den wirkungslosen Ursprungs-Fix. **Noch nicht im Spiel getestet**, siehe `TESTPLAN_0.3.9.9.md`.

## Warum 0.3.9.8 nichts bewirkt hat
`bl4tps_aim status` aus dem Test zeigte:
- `visits = applied = 92` – der Fix war bei jedem Schuss aktiv.
- `last_depth = 3,2 cm` bei 20 cm Rand – der Schussursprung liegt in TPS schon etwa 17 cm vor der Figurenmitte.

Ihn zu verschieben änderte also nichts. Die Flugrichtung entsteht woanders.

## Gemessen (`bl4tps_native_dump`)
Die Feuerrichtung kommt aus Controller-vfunc `0x7A0` (`0xC8D630`).
- **First-Person** (Controller-vfunc `0x788` = Kameradefinition First-Person): Die Funktion liefert die Blickrotation, ohne Trace.
- **TPS:**
  1. `GetPlayerViewPoint` (Controller-vfunc `0x718`) liefert Kameraposition und Blickrichtung.
  2. Der Endpunkt ist `End = Kamera + Blickrichtung × Reichweite`.
  3. `LineTraceSingleByChannel(World, Hit, Start = Kamera, End, Kanal 4)` läuft bei `0xC8DA19`.
  4. Die Rotation zeigt **vom Schussursprung auf den Trefferpunkt** dieses Traces, ohne Treffer auf `End`.

Der Trace startet an der Kamera. Was zwischen Kamera und Figur auf dem Fadenkreuz-Strahl liegt, wird zum Zielpunkt, und die Kugeln fliegen von der Figur genau dorthin: Wandkante neben der Kamera, Gegner im Rücken. Das ist exakt euer Fehlerbild.

## Fix
Der Startpunkt dieses Traces wird vor dem Aufruf entlang der Trace-Richtung auf Figurentiefe plus Rand geschoben:

- `Richtung = normiert(End − Start)`
- `Tiefe = (Pawn − Start) · Richtung + Rand`
- `Start += Richtung × Tiefe`, nur wenn `0 < Tiefe < min(1500 cm, Trace-Länge)`.

Was näher an der Kamera liegt als die Figur, wird nicht mehr abgefragt. Hindernisse vor der Waffe bleiben echte Treffer. Die Pawn-Position kommt in jedem Frame aus dem Spiel, die Kamera-Offsets fließen damit automatisch ein. Der Rand ist standardmäßig 40 cm.

## Native Umsetzung (`native_aim_origin.py`, neu ausgerichtet)
- **Umweg:** Er ersetzt die beiden Argument-Ladebefehle vor dem Trace-Aufruf, `lea r8,[rsp+0x170]; lea r9,[rsp+0x140]` bei `0xC8DA03` (16 Bytes, kein Sprungziel darin).
- **Stub:** Er verschiebt `Start` im Stack-Frame des Aufrufers, aber nur wenn die Korrektur aktiv ist und der Aufrufer der lokale Controller ist. Danach spielt er die beiden Original-Befehle ab und springt nach `0xC8DA13` zurück.
- **Register:**
  - Der Stub nutzt nur `r10`, `r11`, `xmm0`–`xmm5` und Flags.
  - `rax` (World) und `xmm6`–`xmm8` (Endpunkt) bleiben unberührt.
  - Es gibt keinen Aufruf nach außen.
- **Geprüft vor dem Schreiben:** Build, SHA-256 der ganzen Funktion (0x576 Bytes), exakte Original-Bytes und Rücksprung.
- **Restore** beim Ausschalten der Mod.
- **Steuerung:** Konsole unverändert `bl4tps_aim status|on|off|margin <cm>`. Die Status-Zeile heißt jetzt `AIM_TRACE {…}` und enthält `last_start`, `last_shifted` und `last_depth`.
- Der Eingriff aus 0.3.9.8 (`0x40A6ECA`) wird nicht mehr geschrieben.

## Prüfung
- 159 Python-Tests, davon 21 für diesen Fix.
- Der Stub wird auf Linux x64 in einem nachgebauten Frame von `0xC8D630` ausgeführt. Geprüft werden:
  - aus und an
  - schräger Strahl
  - fremder Controller
  - Kamera schon vor der Figur
  - Tiefe jenseits des Trace-Endes
  - Nulllänge und NaN
- Außerdem wird bei jedem Lauf geprüft:
  - `rax` erhalten
  - `r8`/`r9` korrekt
  - Rotation und Endpunkt unberührt
- Ein Disassembler-Test bestätigt, dass nur Scratch-Register geschrieben werden.
- Die Assembler-Quelle liegt in `docs/aim_trace_stub_source.py`.
