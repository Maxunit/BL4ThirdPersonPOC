# BL4ThirdPersonPOC 0.3.9.8 – Zielursprung auf Figurentiefe (alle Projektil- und Hitscan-Waffen)

Basis ist 0.3.9.7. **Erster nativer Fix für das Zielen in TPS. Noch nicht im Spiel getestet**, siehe `TESTPLAN_0.3.9.8.md`.

## Auswertung Runde 3 (statische Probe und Live-Probe AR)
- Der Ziel-Lieferant `Controller +0x448` ist die **Kameraverwaltung**: `aim_provider=['manager']`, vfunc `0x878 = 0x4904A5C`, wie beim Beam gemessen.
- **Korrektur meiner Annahme aus Runde 2:** Interface `+0x38` liefert keinen Zielpunkt, sondern den **Ursprung des Schusses**.
  - vfunc `0x878` prüft nur, ob die aktuelle Kameradefinition First-Person ist (Definition `+0x1C`, Bit 2). In TPS ist das Ergebnis immer `False`. Deshalb meldete die Live-Probe an der Wand und bei freier Sicht `valid=False`.
  - vfunc `0x730` (`0x41E51E0`) gibt die Position aus dem Kamera-Cache zurück (`Manager +0x1910`). Sonst nutzt der Code die Pawn-Sichtposition (Pawn-vfunc `0x718`).
  - Interface `+0x48` berechnet aus diesem Ursprung die Feuerrichtung über Controller-vfunc `0x7A0`. Danach führt die Feuerfunktion den Schuss aus.
- In TPS liegt der Schussursprung also **an der Kamera**. Was auf dem Fadenkreuz-Strahl zwischen Kamera und Figur liegt, wird getroffen: die Wandkante neben der Kamera und der Gegner im Rücken. Das passt genau zu euren Screenshots.

## Fix: Ursprung auf Figurentiefe
- Der Ursprung wird entlang der Blickrichtung der Kamera auf die Tiefe der Figur plus Rand verschoben:
  - `Tiefe = (Pawn − Ursprung) · Blickrichtung + Rand`
  - `neuer Ursprung = Ursprung + Blickrichtung × Tiefe`
  - Das geschieht nur, wenn `0 < Tiefe < 1500 cm` gilt.
  - Der Rand beträgt standardmäßig 40 cm, etwa bis zur Mündung.
- Was vor der Figur zur Kamera hin liegt, kann damit nicht mehr Ziel sein. Hindernisse vor der Waffe bleiben echte Treffer.
- Pawn-Position und Blickrichtung kommen in jedem Frame aus dem Spiel. Die X/Y/Z-Offsets der Kamera aus den Mod-Optionen fließen damit automatisch ein.

## Native Umsetzung
Neu ist `native_aim_origin.py`.
- **Eingriffsstelle:** Ein einziger Umweg ersetzt die 24 Bytes der Ergebniskopie bei `0x40A6ECA` in `0x40A6D12`. Dort treffen sich alle drei Ursprungswege. Kein Sprung zielt in den ersetzten Bereich.
- **Ablauf im Stub:**
  1. Er spielt zuerst exakt die 24 Original-Bytes ab.
  2. Danach verschiebt er den Ursprung, aber nur wenn die Korrektur aktiv ist und der Empfänger genau das Interface des eigenen Pawns ist (`Pawn +0x3A30`).
  3. Dann springt er zurück nach `0x40A6EE2`.
  - Der Stub ruft nichts auf und verändert nur volatile Register.
- **Vor dem Schreiben werden geprüft:**
  - der geprüfte Build
  - der SHA-256-Hash der ganzen Funktion (0x2CC Bytes)
  - die exakten Original-Bytes
  - der Rücksprung
- **Zeitpunkt:** Der Patch wird erst im ersten geeigneten Frame auf dem Game-Thread geschrieben, nicht schon beim Laden der Mod.
- **Steuerblock:** Python schreibt ihn in jedem Frame. Die Korrektur ist aus in diesen Fällen:
  - in First-Person (dieselbe Definitionsprüfung wie `0x878`)
  - im Fahrzeug
  - ohne TPS
  - bei fremdem Pawn
  - bei nicht-endlichen Werten
- **Beim Ausschalten der Mod** kommen die Original-Bytes zurück. Code und Steuerblock bleiben im Speicher reserviert.
- **Konsole:** `bl4tps_aim [status|on|off|margin <cm>]`.
  - `status` zeigt die Zähler `visits`, `applied`, `skipped` und `mismatch` sowie den letzten Ursprung vor und nach der Verschiebung.

## Grenzen
- **Beam-Waffen:** Ihr Ursprung wird vom eigenen Beam-Origin-Patch der Mod auf die Kamera gesetzt. Der Beam verhält sich in dieser Version deshalb **noch unverändert**. Er folgt im nächsten Schritt, sobald die Projektilwaffen bestätigt sind.
- **Spin:** Ob der Kamera-Spin damit verschwindet, zeigt erst der Test.

## Prüfung
- 158 Python-Tests, davon 19 neu.
  - Der Stub wird auf Linux x64 **tatsächlich ausgeführt**, in einem nachgebauten Funktionsrahmen. Geprüft werden:
    - aus
    - an
    - schräge Blickrichtung
    - fremder Empfänger
    - Ursprung schon vor der Figur
    - unplausible Tiefe und NaN
  - Weitere Tests decken Folgendes ab:
    - Install und Restore mit Ablehnungen
    - Gates im Frame
    - Neuinstallation
    - verwaiste Owner
    - Konsole
    - Loader-Verdrahtung
    - Abgleich der Assembler-Quelle `docs/aim_origin_stub_source.py` mit dem ausgelieferten Stub
- Ein unabhängiges Review fand keine ernsten Fehler am nativen Teil. Drei kleine Python-Punkte daraus sind behoben:
  - Der Steuerblock wird jetzt in jedem Frame aktiviert.
  - Ein Installationsfehler hat Vorrang.
  - Der Restore beim Aktivieren ist abgesichert.
