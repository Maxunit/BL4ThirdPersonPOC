# BL4ThirdPersonPOC 0.3.9.6 – Messrunde 2: gemeinsame Zielabfrage aller Waffen

Basis ist 0.3.9.5. **Keine Änderung am Spielverhalten.** Erweitert wird nur der lesende Befehl `bl4tps_weapon_probe`. Testplan: `TESTPLAN_0.3.9.6.md`.

## Auswertung Runde 1 (Beam, SMG Bienen, Shotgun Minigranaten, AR Hitscan)
- Alle drei Nicht-Beam-Waffen nutzen dieselbe Feuerklasse `WeaponBehavior_FireProjectile`, Slot `0x410 = 0x43459D4`. Das gilt auch für das „Hitscan“-AR. Ein einziger Fix kann also alle drei abdecken.
- Der Beam (`WeaponBehavior_FireBeam`, Slot `0x410 = 0x4344586`) durchläuft am Anfang dieselbe Kette.
- Feuerablauf, gemessen per Disassembly:
  1. Slot `0x410` (Benutzen) ruft Slot `0x2C0` (Zielpunkt) auf.
  2. Slot `0x2C0` fragt das **Waffenhalter-Interface** der Waffe (`OakWeapon +0xB18/+0xB20`) über dessen Slot `+0x38` nach dem Zielpunkt. Gibt es keinen gültigen Punkt, nimmt er die Mündung (Slot `0x2C8`, Socket-Position).
  3. `0x3EC656E` berechnet aus dem Zielpunkt die Feuerrichtung, über Interface-Slot `+0x48`, ersatzweise über Pawn-Vfunc `0x720`.
  4. Danach folgen das Spawnen (Slot `0x490`) und der Vergleich Zielpunkt gegen Mündung.
- Folgerung: Der Zielpunkt entsteht an genau einer gemeinsamen Stelle, dem Interface-Slot `+0x38`. Liefert er einen Punkt zwischen Kamera und Figur, schießt die Waffe dorthin.

## Neuer Befund im Spiel: Wandkante neben der Figur
Steht die Figur dicht an einer Wand und liegt das Fadenkreuz über der Wandkante, treffen die Projektile die Wand neben der Figur statt geradeaus zu fliegen. Beim Beam passiert dasselbe.

Das ist derselbe Mechanismus wie beim Gegner hinter der Figur. Die Zielabfrage startet an der Kamera und nimmt den ersten Treffer auf dem Fadenkreuz-Strahl, auch wenn er näher an der Kamera liegt als die Waffe.

**Lösungsansatz (Z-Tiefen-Abfrage, als Trace umgesetzt):** Die Zielabfrage startet erst in der Tiefe der Mündung, also bei der Projektion der Mündung auf den Kamerastrahl. Alles, was in Blickrichtung vor dieser Tiefe liegt, kann nicht mehr Ziel sein. Dazu gehören Gegner im Rücken, Wandkanten neben der Kamera und Deckung zwischen Kamera und Figur. Hindernisse vor der Mündung bleiben echte Treffer.

Einen echten Tiefenpuffer gibt es für die Mod nicht. Die Tiefe ergibt sich deshalb aus dem Abstand entlang des Strahls.

## Neu in der Probe (Version 2)
- **Waffenhalter-Interface:**
  - Objekt und Interface-Zeiger
  - Zuordnung zu Pawn, Controller oder Manager
  - Interface-Vtable mit 32 Slots
  - tiefe Code-Ernte ab den Slots `+0x30` bis `+0x50`: 0x1000 Bytes je Funktion, Tiefe 4, höchstens 260 Funktionen, getrennt von der Feuer-Ernte
- **Feuerkette in voller Länge:** Slot `0x410` (0x2400 Bytes), `0x490` (0x1000), `0x2C0` und `0x2C8`.
- **Kamera-Cache-Marken** decken jetzt den ganzen POV-Bereich `+0x1900` bis `+0x1960` ab, also Position und Rotation.
- Die Feuer-Ernte ist auf 160 Funktionen gesenkt. Runde 1 hat gezeigt, dass Override-Slots das Budget sonst früh verbrauchen.

## Sicherheit
Unverändert:
- nur `ReadProcessMemory`;
- nur der geprüfte Build;
- keine Hooks und keine Patches.

## Tests
- 133 Python-Tests, davon 4 neu:
  - Halter auflösen und tief ernten
  - fehlender Halter
  - Feuerfenster in voller Länge
  - Ablauf von `run` mit den Feldern der Konsolenzeile
