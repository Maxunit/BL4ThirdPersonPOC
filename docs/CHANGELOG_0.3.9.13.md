# BL4ThirdPersonPOC 0.3.9.13 – Testversion „Hybrid ADS Mode“ (Omni)

Basis ist 0.3.9.12. **Testversion, noch nicht im Spiel geprüft**, siehe `TESTPLAN_0.3.9.13.md`.

Die Option ist standardmäßig **aus**. Ist sie aus oder läuft Omni nicht, verhält sich alles wie in 0.3.9.12.

## Bedienungskonzept (09.10.2026)
- **Zielen halten** (L2 bzw. rechte Maustaste, also die im Spiel belegte Zieltaste):
  - Die Figur legt die Waffe an und Omni pausiert. Links/rechts strafed, die Figur dreht sich nicht weg.
  - Die Kamera rückt etwas näher an die Schulter und zoomt leicht.
- **Sprint während des Zielens** (L3 bzw. Shift, also die im Spiel belegte Sprint-Taste): schaltet in das native Scope der Waffe in der First-Person-Perspektive. Ein weiterer Sprint-Druck führt zurück ins Schulterzielen.
- **Zieltaste loslassen:** zurück zu Omni, auch direkt aus dem Scope.
- **Regeln:**
  - Ein Waffenwechsel im Scope führt zurück ins Schulterzielen.
  - FFYL, Fahrzeug, Menü, Slide und Leiter beenden alles wie bisher.
  - Scharfschützengewehre gehen im Hybrid-Modus nicht mehr direkt in den Scope.
- **Sprint-Taste:** BL4 ignoriert Sprint, solange gezielt wird. Die Mod liest die Sprint-Taste deshalb nur mit und blockiert nichts.

## Umsetzung
- **Neues Modul `hybrid_ads.py`:**
  - **Aktiv**, wenn die Option an ist, Omni läuft und Omnis Gameplay-Sitzung gebunden ist. Nur diese Sitzung liest die Sprint-Taste. Direkt nach einem Fahrzeugausstieg gelten deshalb kurz die normalen ADS-Regeln, bis Omni wieder übernimmt.
  - **Halten:** Alle Waffen nehmen die vorhandene TPS-ADS-Route, auch Scharfschützengewehre.
    - Omni pausiert dabei schon heute, denn ADS ist ein Kampf-Signal.
    - Der TPS-Zoom ist auf 1,35× gedeckelt.
    - Die Kamera fährt 35 cm näher (Offset +X, höchstens auf 110). Die Annäherung läuft synchron zum ADS-Zoom ein und aus.
  - **Scope an:** derselbe Ablauf wie der vorhandene TPS→Scharfschützen-Wechsel beim Waffenwechsel.
    - TPS-Look-Owner abgeben, ADS-Zustand und Übergabe aufräumen.
    - Route `sniper_fps` bzw. `fallback_fps`.
    - `SetActorCameraMode(Default)` mit 0,2 s Überblendung.
    - Erst der Kamerawechsel, dann die Zustandsänderung. Scheitert der Aufruf, bleibt alles, wie es war.
    - Kamera-Offset und FOV-Offset blenden über dieselben 0,2 s aus, statt zu springen.
  - **Scope aus:** `SetActorCameraMode(ThirdPerson)` mit 0,2 s Überblendung und eine Routenübergabe mit Kennung „gleiche Waffe“.
    - Die vorhandene Routen-Abstimmung startet TPS-ADS, sobald die Überblendung fertig ist. So wird der Basis-FOV nicht mitten im Blend gelesen.
    - Ohne Equip-Gate, weil keine Equip-Callbacks folgen.
    - Der TPS-Rückstoß-Owner (und damit die Beam-Korrektur) wird für den Rest des Haltens wieder aktiviert: neue Anfrage „gleiche Waffe“ an den vorhandenen Held-ADS-Rearm (`HELD_ADS_REARMED source=hybrid_scope_exit`).
  - **Loslassen im Scope:** Die vorhandene FPS-Freigabe nutzt dann 0,2 s statt 0,06 s und blendet den Offset ein.
  - **Waffenwechsel im Scope:** Die vorhandene Rückkehr nach TPS nutzt im Hybrid-Modus ebenfalls 0,2 s mit Einblendung und wartet auf das Ende der Überblendung, bevor sie den Basis-FOV liest.
  - **Überblendungen** starten immer beim tatsächlich anliegenden Kamera-Offset und laufen zum aktuellen Ziel. Die Rückkehr hält den Hüft-Offset, solange noch First-Person aktiv ist oder die Kamera noch blendet. Es gibt also keinen Frame mit Offset 0.
  - **FOV-Überblendung** endet bei jedem Abbruch (Kontextwechsel, neues TPS-ADS, Mod aus) mit dem nativen Endwert.
- **Omni** erkennt den Sprint-Druck einmal pro Druck in `read_combat` (`observe_hybrid_scope`). Das gilt nur bei aktivem ADS und eingeschalteter Option.
- **Kein Timer:** Jeder Zustandswechsel wird von einer Taste oder einem beobachteten Kameramodus ausgelöst. Die 0,2 s sind nur die Animationsdauer der Überblendung.
- **Kein neuer Speicherzugriff, kein nativer Patch.**

## Bedienung
- **F7 → CAMERA MODES → MOVEMENT (EXPERIMENTAL):** neue Zeile „Hybrid ADS Mode: ON/OFF“.
- **Konsole:** `bl4tps_omni hybrid on|off|status|dolly <cm>|zoom <x>`.
  - `dolly` ist die Annäherung beim Halten, 0–100 cm, Standard 35.
  - `zoom` ist der Zoom-Deckel beim Halten, 1,0–4,0, Standard 1,35.
  - Die Feinwerte gelten bis zum Spielneustart. Die Option selbst wird gespeichert.
- **Konsolenzeilen:**
  - `HYBRID_SCOPE_ON route=… zoom_state…`
  - `HYBRID_SCOPE_OFF …`
  - `HYBRID_SCOPE_REFUSED reason=…`
  - `HYBRID_ADS_ROUTE_MIGRATED … gate='hybrid_scope_exit'`
  - `OMNI_HYBRID_ADS {…}` mit Zählern

## Bekannte Grenzen der Testversion
- **Scope:** Ob das native Scope beim Wechsel aus dem gehaltenen Schulterzielen vollständig erscheint, also mit Zoom, Zielfernrohr und HUD, ist ungeprüft. Die native Zoom-Meldung wurde während des Schulterzielens bewusst unterdrückt. Die Zeile `HYBRID_SCOPE_ON` protokolliert den Zoom-Zustand dafür.
- **Hüftfeuer:** Das kurze Hin- und Wegdrehen beim Hüftfeuer bleibt, denn Hybrid ADS ändert nur das Zielen.

## Prüfung
- 241 Python-Tests, davon 29 neu in `test_hybrid_ads_0_3_9_13.py`:
  - Gates
  - Zoom-Deckel
  - Annäherung
  - Scope an/aus mit allen Ablehnungen
  - Überblendungen
  - Omni-Auslöser
  - Routen-Abstimmung „gleiche Waffe“ und Waffenwechsel im Scope
  - Held-ADS-Rearm mit Anfrage „gleiche Waffe“
  - Option/Konsole im Loader
- Alle Loader-Szenarien bestehen.
- Ein unabhängiges Review lief über die Änderungen. Umgesetzt daraus:
  - Rearm nach Scope-Rückkehr
  - lückenlose Überblendungen
  - FOV-Endwert bei Abbruch
  - Kamerawechsel vor Zustandsänderung
  - Waffenwechsel im Scope
  - strengere Aktivitätsprüfung
