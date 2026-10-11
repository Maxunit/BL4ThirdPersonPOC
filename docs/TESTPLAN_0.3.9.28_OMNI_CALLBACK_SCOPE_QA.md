# 0.3.9.28 – Testplan Omni Callback-Scope

Spiel vollständig beenden; alte Mod-Dateien und PyCache entfernen.
Eine Variante installieren: `dist/BL4ThirdPersonPOC.sdkmod` oder den Quellordner.

## 1. Messung (wichtigster Teil)

1. Gleiche Stelle und gleicher Blick wie bei den .26/.27-Aufnahmen.
   Normale TPS, UI zu, `bl4tps_omni diag off`.
2. **Zusätzlich ohne 120-FPS-Limit messen** (NVIDIA-Limit kurz aus, FrameGen an
   lassen). Mit Limit zeigt die Anzeige nur den Teil des Verlusts, der über die
   Reserve hinausgeht. Ohne Limit sieht man den echten Abstand Omni aus/an.
3. FPS Omni aus, dann Omni an notieren (mit und ohne Limit).
4. `bl4tps_omni profile total idle_a` → Konsole zu → F10 → stehen bleiben bis
   zum automatischen Ende (600 Updates).
5. `bl4tps_omni profile detail idle_detail`, dann `bl4tps_omni profile total idle_b`.
6. Dasselbe einmal **in der Hocke** (`total crouch_a`).

Zurückgeben: die JSONs aus `sdk_mods/settings/BL4ThirdPersonPOC_reports` und die FPS.
Vergleichswerte .26 Total: 4,07 / 4,02 ms. Im Detail sollte `runtime.bound` jetzt
viele sehr billige Aufrufe zeigen und `native.process_read` deutlich weniger Reads.

## 2. Regressionscheck

- WASD und Stick, Sprint, Ground-Dash, Jump/Air-Dash, Slide, Slam, Crouch-Drehen.
- Schießen aus Sprint, Nachladen, Waffentausch, Granate, Objektwurf.
- Hold- und Toggle-ADS mit Hybrid-Scope per Sprint: Reticle weg im Scope, wieder da.
- **Gamepad:** Fire und Zoom auf den Triggern leicht antippen. Ansprechen wie in .27?
  Tastatur und Maus: alle Aktionen wie vorher?
- UI/Shop, Leiter, Fahrzeug ein/aus, TPS/FPS-Wechsel, Respawn/Mapwechsel.
- Eine Aktion im Menü umbelegen, zurück ins Spiel: neue Taste muss sofort greifen.
- Omni aus/an: sauber neu binden.
- `bl4tps_omni report` nach einer Runde: `errors` leer? Unter
  `current_gameplay.input_mapping_history[-1].key_reads` steht pro Rolle die
  Abfrageart je Taste. Steht dort überall `both`, hat die Einordnung im Spiel
  nicht gegriffen (alter Weg, korrekt, nur ohne diese Einsparung).
