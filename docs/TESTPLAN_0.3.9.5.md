# Testplan 0.3.9.5 – Messrunde Projektil-/Hitscan-Zielpfad

Installation wie bisher: die `.sdkmod` ersetzen und `__pycache__` löschen. Diese Version ändert nichts am Spielverhalten. Die beiden neuen Befehle lesen nur.

## 1. Proben aufnehmen
Jede Probe läuft im normalen TPS, ohne ADS, mit der jeweiligen Waffe in der Hand. Nach jedem Waffenwechsel einmal `bl4tps_weapon_probe` eingeben. In der Konsole erscheint `WEAPON_PROBE … fire_class=…` und danach der Dateipfad.

Bitte diese Waffen proben, insgesamt höchstens 12, weil nur die neuesten 12 Dateien erhalten bleiben:
1. **Eine Beam-Waffe**, falls vorhanden. Sie dient als Referenz, dort ist der Pfad bekannt.
2. **Die Waffe, bei der die Projektile nach hinten geflogen sind.**
3. Je eine weitere Waffe pro Typ: Pistole, SMG, Sturmgewehr, Schrotflinte, Scharfschützengewehr, Raketenwerfer.
4. Wenn möglich verschiedene Hersteller, zum Beispiel Jakobs, Torgue, Vladof, Maliwan und Tediore.

## 2. Notizen zum Fehler
Bitte für die Waffen aus Punkt 1 kurz notieren:
- Fliegen Projektile nach hinten, wenn ein Gegner oder Objekt dicht hinter der Figur steht? Ja oder nein.
- Kamera-Spin:
  - Tritt er nur beim Feuern auf, oder schon beim Zielen auf den Gegner hinter der Figur?
  - Tritt er in der Hüfte, in ADS oder in beidem auf?
  - Mit welcher Waffe passiert es?

## 3. Zurückschicken
- Alle `weapon_probe_*.json` aus `sdk_mods/settings/BL4ThirdPersonPOC_reports/`.
- Die Notizen aus Punkt 2.
- Sobald ich die Dateien ausgewertet habe, schicke ich eventuell eine kurze Liste mit `bl4tps_native_dump …`-Befehlen zum Kopieren.
