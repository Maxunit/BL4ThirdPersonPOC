# Testplan 0.3.9.12 – Beam-Tiefe, Throwables mit Omni, Sprint-Feuer

Installation wie gewohnt: das Spiel ganz beenden, die `.sdkmod` ersetzen und `__pycache__` löschen.

Die Nachtests aus `TESTPLAN_0.3.9.10.md` und `CHANGELOG_0.3.9.11.md` (freier Fall) gelten weiter. Diese Punkte kommen dazu.

## 1. Start
- In TPS erscheint einmal `[BL4ThirdPersonPOC.AimTrace] ARMED rva=0xC8DA03 native_patches=1`.
- Mit Beam-Waffe in der Hand erscheint `[BL4ThirdPersonPOC.BeamOrigin] BEAM_DEPTH enabled=True reason=armed rotation=0x…`.
- Steht dort `enabled=False`, bitte die ganze Zeile schicken. Der Beam verhält sich dann wie in 0.3.9.11.

## 2. Beam an der Wandkante
1. Dieselbe Stelle wie auf euren Screenshots, mit dem Beam feuern.
2. **Erwartet:** Der Beam geht nach vorn zum Fadenkreuz und endet nicht an der Wand neben der Figur.
3. Zum Vergleich `bl4tps_aim off` (schaltet Kugel- und Beam-Korrektur ab), danach `bl4tps_aim on`.
4. Danach `bl4tps_aim status` und die Zeile `AIM_TRACE {…}` schicken. Unter `beam` sollte `applied` steigen.

## 3. Beam aus der Nähe, durch Deckung und im Rücken
- Gegner etwa 1 m vor der Figur: wird er getroffen?
- **Deckung:** Direkt vor eine dünne Wand oder Deckung stellen (etwa 0,5 m) und auf einen Gegner dahinter zielen.
  - Mit Rand 70 kann der Beam hindurchgehen.
  - Bitte notieren, ob das passiert, und dasselbe mit `bl4tps_aim beam_margin 30` wiederholen.
  - Mit 30 bitte auch noch einmal die Wandkante aus Punkt 2 prüfen. So finden wir den besten Standard.
- Gegner oder Objekt direkt hinter der Figur: kein Treffer hinter euch, kein Kamera-Spin.

## 4. Beam-Regression
- TPS-ADS mit Beam
- Slide mit Beam
- Waffenwechsel Beam ↔ andere Waffe
- FPS ↔ TPS
- Fahrzeug

Es dürfen keine Fehlerzeilen von `BeamOrigin` oder `BeamCollision` auftauchen.

## 5. Throwables mit Omni (Omni an)
1. Granate werfen: im Stehen, beim Seitwärts- und Rückwärtslaufen, kurz antippen und gehalten.
2. **Erwartet:** Der Körper dreht sich beim Wurf zur Blickrichtung und danach wieder in die Laufrichtung.
3. Kanister oder anderes Throwable aufheben und werfen, ebenfalls beim Seitwärtslaufen.
4. **Konsole:** Für die ersten Würfe erscheint `THROW_HOLD source=gadget montage=…` oder `source=throwable_fire`. Bitte diese Zeilen schicken. Steht dort `THROW_NO_MONTAGE`, bitte auch melden.
5. Mit Heavy Weapon auf der Ordnance-Taste, falls vorhanden: Ausrüsten darf Omni nicht stören.

## 6. Sprint-Feuer (Omni an)
- **Gamepad:** im Seitwärtssprint den Feuer-Trigger nur ganz leicht andrücken und loslassen.
  - Erwartet: Der Sprint läuft weiter.
  - Konsole: `SPRINT_FIRE_NOT_ADMITTED reason=NO_NATIVE_REQUEST`.
- **Leeres Magazin** wie in 0.3.9.4: Seit- und Rückwärtssprint, feuern, loslassen. Der Sprint läuft weiter.
- **Normale Waffe und Charge-AR** aus dem Seitwärtssprint: Die Schüsse gehen in Blickrichtung.
- **Direkt nach dem Feuern aus dem Sprint** Waffe wechseln, nachladen und eine Tediore werfen.
  - Omni darf nicht stoppen.
  - Eine Warnung `SPRINT_FIRE_NATIVE_UNAVAILABLE` ist erlaubt. Bitte schicken, falls sie kommt.

## 7. Abschluss
`bl4tps_omni report` und das Session-Log schicken.
