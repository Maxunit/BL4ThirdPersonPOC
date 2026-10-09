# BL4ThirdPersonPOC 0.3.9.3 – Shop ohne Native-Fehler, Interaktion folgt Action_Use

Basis ist 0.3.9.2, das im Spieltest weitgehend sauber war. **Im Spiel bestätigt am 09.10.2026** (Testplan `TESTPLAN_0.3.9.3.md`, alle Punkte ohne Befund).

## Shop: Ursache der gemeldeten „TPSRecovery“
Die Meldung nach dem Shop kam **nicht** vom neuen Modul `[BL4ThirdPersonPOC.TPSRecovery]`. Im Log gibt es keine Zeile mit diesem Tag. Gemeint war `NATIVE_FAULT_RECOVERED reason=settled_tps_recovery`. Das ist ein vorhandener Sicherheitspfad der Hauptmod und war schon in 0.3.8.17 so, der Code ist unverändert.

Ablauf bis 0.3.9.2:
1. `ClientSetCurrentInteractable(OakVendingMachine)` läuft als POST-Hook. BL4 hat zu diesem Zeitpunkt den Interaktionsmodus `StructuredInteraction` schon auf den Kamera-Stack gelegt.
2. Beim TPS-Pop für den Shop prüft der Recoil-Restore den Stack. Er erkennt den fremden Eintrag nicht und verweigert das Zurückschreiben, wie vorgesehen. Im Log steht dann `ERR NATIVE_RESTORE_FAILED reason=camera_pop:requested`.
3. Nach dem Shop, sobald TPS wieder ruhig steht, gelingt der Restore. Im Log steht dann `NATIVE_FAULT_RECOVERED reason=settled_tps_recovery`.

Spielbar war das schon vorher. Es gab aber bei jedem Shop-Besuch eine ERR-Zeile und einen kurzen Native-Fehlerzustand.

**Änderung:** Für Quest-NPCs gab es schon einen Restore vor `ServerUseObject` (`npc_server_use_pre`). Dieser greift jetzt auch für `OakVendingMachine` (`shop_server_use_pre`). Der Restore läuft also, solange der Stack nur TPS enthält. Danach hält der vorhandene Mechanismus (`npc_native_resume`) das Wiederanlegen zurück, bis die Benutzung abgeschlossen ist. Erneut angelegt wird erst wieder in ruhigem TPS nach dem Shop. Schlägt der frühe Restore fehl, bleibt der bisherige Ablauf als Rückfallebene bestehen, mit WARN statt „Spiel neu starten“.

## Interaktion folgt `Action_Use`
- Bestätigt mit `bl4tps_actions all` vor dem Automaten: `Action_Use: E, Gamepad_FaceButton_Left`.
- Die Interaktions-Keybinds (Maus/Tastatur und Gamepad getrennt) folgen jetzt dieser Aktion, genau wie ADS `Action_Zoom` folgt.
- `Action_Use` hat nur dann Mapping-Zeilen, wenn ein Interaktionsziel in der Nähe ist. Abseits davon bleibt die zuletzt gültige Taste (`KEPT_NO_CONFIGURED_KEY`). Bei der nächsten Mapping-Änderung wird wieder abgeglichen.

## Diagnose des Tasten-Abgleichs
- Im Log stand `ACTION_KEY_SYNC syncs=0`, in 0.3.9.0 waren es 190. Die Ursache ist aus dem Log nicht ablesbar. Es gab keinen Fehler, und der Owner war aktiv.
- `bl4tps_actions` gleicht jetzt sofort ab: auf dem Game-Thread und vor dem Bericht. Fehlt die Widget-Route, wird sie neu angelegt (`ROUTE_RESTORED`).
- Der Bericht enthält jetzt zusätzlich:
  - `frames`
  - `skips` nach Grund (`not_game_thread`, `cursor_shown`, `no_controller`, `no_player_input`)
  - `route_registered`
  - `route_restores`
- Mit Standardtasten hatte `syncs=0` keine spürbare Wirkung, weil die Keybinds schon auf den konfigurierten Tasten lagen.

## Ausgewertet, keine Änderung nötig
- **Slides (`slide_exit_cycles`, 9 Slides):** Der Halt nach dem Slide dauert 8–9 Updates. Die native Drehung zur Kamera hätte den Körper um bis zu 165° gedreht. Gehalten wurden die Slide-Richtung oder ein kleiner Schritt in Bewegungsrichtung. Bei Vorwärts-Slides lag die Abweichung bei ≈0°. Der Fix wirkt.
- **Save/Load:** Die Reparatur kam etwa 16 s nach dem Laden. Das ist die Dauer des Ladebildschirms: Die Reparatur lief im selben Moment, in dem die Welt bereit war (PickupRegistry RESUMED, Omni WAITING_CAMERA_TRANSITION). Es gibt also keine zusätzliche Wartezeit.
- **Respawn:** `CLIENT_RESTART_SEEN … tps_enabled=True` und danach `CAMERA_LIFECYCLE_ARMED reason='client_restart'`. Der Pfad zur Respawn-Kamera wird erreicht.

## Tests
- 110 Python-Tests, davon 10 neu.
- Ein Ende-zu-Ende-Lauf über den echten Loader (Shop-Benutzung) prüft:
  - genau ein PRE-Restore;
  - kein zweiter Restore beim Pop;
  - die Wiederanlage wird gehalten;
  - der NPC-Pfad ist unverändert;
  - eine Kiste löst nichts aus.
