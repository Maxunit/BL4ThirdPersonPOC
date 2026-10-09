# Testplan 0.3.9.3 (kurzer Nachtest)

Installation wie bisher: die `.sdkmod` ersetzen und `__pycache__` löschen. Omni bleibt an, `diag` ist nicht nötig.

## 1. Shop
1. In TPS an einen Automaten gehen, den Shop öffnen, kurz warten und wieder schließen. Das Ganze zweimal.
2. Erwartet: wie bisher keine sichtbare Änderung, TPS kommt nach dem Shop zurück.
3. In der Konsole sollte stehen:
   - `NATIVE_STOP reason=shop_server_use_pre`
   - danach `NPC_NATIVE_USE_COMPLETED` (der Name ist historisch und gilt hier auch für den Shop)
   - nach dem Shop `NATIVE_ON recoil=True`
4. Nicht erwartet:
   - `NATIVE_RESTORE_FAILED`
   - `NATIVE_FAULT_RECOVERED reason=settled_tps_recovery`
   - `SHOP_NATIVE_PRE_RESTORE_FAILED`
5. Hinweis zur Suche: Das neue Reparaturmodul schreibt immer mit dem Tag `[BL4ThirdPersonPOC.TPSRecovery]`. `settled_tps_recovery` gehört zum Recoil-Pfad der Hauptmod.

## 2. Quest-NPC (Regression)
1. Mit einem Quest-NPC sprechen und das Gespräch beenden.
2. Erwartet: wie bisher. Im Log steht `NATIVE_STOP reason=npc_server_use_pre`.

## 3. Interaktion
1. Vor einer Kiste oder einem Automaten `bl4tps_actions` eingeben.
2. Erwartet in `ACTION_KEY_SYNC`:
   - `syncs` ist größer als 0;
   - `interact/kbm` hat `asset: 'Action_Use'`, `key: 'E'`, `status: 'FOLLOWING'`;
   - `interact/gamepad` steht entsprechend auf `Gamepad_FaceButton_Left`.
3. Mit E bzw. Viereck interagieren, auch auf Ziele in Fadenkreuzrichtung. Alles soll wie bisher funktionieren.
4. Optional: In den Spieleinstellungen „Benutzen“ auf eine andere Taste legen, vor einem Automaten `bl4tps_actions` eingeben und mit der neuen Taste interagieren. Danach die Taste zurückstellen.

## 4. Abgleich-Diagnose
1. Nach etwa einer Minute normalem Spiel `bl4tps_actions` eingeben, **bevor** du vor einem Interaktionsziel stehst.
2. Bitte die ganze Zeile `ACTION_KEY_SYNC` schicken. Wichtig sind `frames`, `skips`, `route_registered` und `route_restores`.
3. Falls `ACTION_KEY_SYNC_NOW skipped=…` oder `ROUTE_RESTORED` erscheint, bitte diese Zeilen ebenfalls schicken.

## Was zurückschicken
- Die Shop-Zeilen aus Punkt 1.
- Die `ACTION_KEY_SYNC`-Zeilen aus Punkt 3 und 4.
