# Testplan 0.3.9.13 – Hybrid ADS Mode (Testversion)

Installation wie gewohnt: das Spiel ganz beenden, die `.sdkmod` ersetzen und `__pycache__` löschen.

Omni einschalten. Dann **F7 → CAMERA MODES → „Hybrid ADS Mode“ → TOGGLE** oder `bl4tps_omni hybrid on`.

Die Punkte aus `TESTPLAN_0.3.9.12.md` gelten weiter, falls noch offen.

## 1. Halten (Schulterzielen)
- **Erwartet bei gehaltenem L2 bzw. rechter Maustaste:**
  - Die Figur schaut in Blickrichtung, und links/rechts wird gestrafed.
  - Die Kamera rückt weich etwas näher und zoomt leicht.
- **Loslassen:** Die Kamera fährt weich zurück, und Omni übernimmt wieder.
- **Mit einem Scharfschützengewehr:** Auch hier erst Schulterzielen, kein sofortiger Scope.
- **Feinwerte:** `bl4tps_omni hybrid dolly 20` bzw. `dolly 60` und `bl4tps_omni hybrid zoom 1.1` bzw. `zoom 1.6`. Bitte sagen, welche Werte sich am besten anfühlen.

## 2. Scope per Sprint-Taste
1. L2 halten, dann L3 bzw. Shift drücken.
   - Erwartet: Die Kamera blendet in die First-Person-Perspektive und den Scope der Waffe.
   - Konsole: `HYBRID_SCOPE_ON …`. Bitte die ganze Zeile schicken.
2. **Prüfen:**
   - Ist die Sicht wirklich gezoomt?
   - Erscheint das Zielfernrohr beim Scharfschützengewehr bzw. die Kimme beim AR?
   - Stimmt das HUD?
3. Noch einmal L3 bzw. Shift drücken, L2 bleibt gehalten.
   - Erwartet: zurück ins Schulterzielen.
   - Konsole: `HYBRID_SCOPE_OFF`, danach `HYBRID_ADS_ROUTE_MIGRATED … gate='hybrid_scope_exit'` und `HELD_ADS_REARMED source=hybrid_scope_exit`.
   - Danach weiter schießen: Der Rückstoß in TPS soll sich wie beim normalen Schulterzielen anfühlen.
4. Im Scope L2 loslassen. Erwartet: weiche Rückkehr in Omni-TPS.
5. Mehrfach schnell hin und her schalten. Ein Druck während einer laufenden Überblendung wird abgelehnt (`HYBRID_SCOPE_REFUSED reason=camera_transitioning`), danach einfach noch einmal drücken.
6. Nach dem Loslassen von L2 darf die Figur nicht von selbst lossprinten.

## 3. Sonderfälle
- **Waffenwechsel im Scope:** Erwartet ist die Rückkehr ins Schulterzielen mit der neuen Waffe.
- **Im Scope:** nachladen, schießen, Beam, Slide-Versuch.
- **FFYL, Fahrzeug, Menü (F7), Leiter** während des Zielens und im Scope: Alles muss sauber in den normalen Zustand zurückfinden.
- **Hybrid aus** (`bl4tps_omni hybrid off`): Das Verhalten ist wie in 0.3.9.12, Scharfschützengewehre gehen wieder direkt in den Scope.
- **Omni aus:** Hybrid hat keine Wirkung.

## 4. Abschluss
`bl4tps_omni hybrid status`, `bl4tps_omni report` und das Session-Log schicken.
