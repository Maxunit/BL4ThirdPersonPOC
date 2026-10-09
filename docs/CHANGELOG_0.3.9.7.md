# BL4ThirdPersonPOC 0.3.9.7 – Messrunde 3: Zielpunkt der Kameraverwaltung

Basis ist 0.3.9.6. **Keine Änderung am Spielverhalten.** Erweitert wird nur `bl4tps_weapon_probe`. Testplan: `TESTPLAN_0.3.9.7.md`.

## Auswertung Runde 2 (AR, Beam, Shotgun)
- Der Waffenhalter ist bei allen drei Waffen der **Pawn** (`OakCharacter`). Sein Interface liegt bei `+0x3A30`, die Vtable-RVA ist `0xB6F55F0`.
- Interface-Slot `+0x38` (`0x40A6D12`) liefert den Zielpunkt so:
  1. Er holt den lokalen Controller (`Pawn +0x3C0`) und prüft dessen Klasse.
  2. Er holt den **Ziel-Lieferanten** `Controller +0x448`.
  3. Er fragt dessen vfunc `0x878`, ob ein gültiges Ziel vorhanden ist.
  4. Er liest über dessen vfunc `0x730` den Zielpunkt als Vektor, setzt das Gültig-Flag und gibt den Punkt zurück.
  5. Ersatzweise nimmt er die Pawn-vfunc `0x718`.
- Der Beam-Owner hatte bereits `OakPlayerCameraManager` vfunc `0x878 = 0x4904A5C` als Teil der Kamera-Kette validiert. Der Ziel-Lieferant ist also sehr wahrscheinlich die **Kameraverwaltung selbst**. Der Zielpunkt aller Waffen stammt damit aus der Kamera-Zielabfrage. Das passt genau zu den Fehlerbildern: Wandkante an der Kamera und Gegner im Rücken.

## Neu in der Probe (Version 3)
- **Ziel-Lieferant `Controller +0x448`:**
  - Adresse und Abgleich mit Manager, Pawn und Controller
  - Vtable mit 320 Slots
  - `aim_valid` (0x878) und `aim_target` (0x730)
  - Abgleich mit der Beam-Messung
  - Pawn-Fallback `0x718`
- Tiefe Code-Ernte ab `0x730`, `0x878` und dem Pawn-Fallback: 0x1000 Bytes je Funktion, Tiefe 3, höchstens 260 Funktionen. Die Halter-Ernte ist auf 40 Funktionen gesenkt, weil sie bekannt ist.
- **`bl4tps_weapon_probe live`** (optional) ruft die beiden Getter der Kameraverwaltung **einmal** auf. Der Aufruf geschieht genau so, wie das Spiel selbst sie aufruft (`rcx` = Manager, `rdx` = Ausgabepuffer). Danach setzt der Befehl den Zielpunkt ins Verhältnis zu Kamera und Pawn:
  - Abstand
  - Tiefe entlang der Blickrichtung
  - `target_in_front_of_pawn`
  - Der Aufruf läuft nur, wenn der Lieferant die gemessene Kameraverwaltung ist. Den Zielpunkt fragt er nur ab, wenn `0x878` ein gültiges Ziel meldet. Das Modul schreibt keinen Spielspeicher.
  - Konsole: `WEAPON_PROBE_LIVE valid=… target_distance=… target_depth=… pawn_depth=… target_in_front_of_pawn=…`

## Zur einstellbaren Kameradistanz (X/Y/Z-Offsets)
Der spätere Fix rechnet in jedem Frame mit der tatsächlichen Kamera- und Pawn-Position. Die Offsets aus den Mod-Optionen fließen damit automatisch ein, und es wird kein fester Abstand angenommen.

## Tests
138 Python-Tests, davon 5 neu:
- Lieferant als gemessene Kameraverwaltung
- Lieferant-Fehler bricht die Probe nicht ab
- Live-Auswertung mit Tiefen
- kein Zielaufruf bei ungültigem Ziel
- kein Live-Aufruf ohne gemessene Kameraverwaltung
