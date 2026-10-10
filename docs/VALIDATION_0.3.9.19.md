# Lokale Prüfung – 0.3.9.19 QA

Geprüft am 10.10.2026. Basis 0.3.9.18; kombinierte SDKMOD noch ohne Spieltest.

- `python -m unittest discover -s tests -v`: 332 Tests, erfolgreich; 4 bestehende,
  umgebungsabhängige Tests übersprungen. 19 zusätzliche projektinterne Tests betreffen
  Cache-Grenzen, tatsächliche Pre-Copy-Protection-Freigabe, Fehler/Rückbau,
  gepaarte Exit-Tickets, Original-Templates und die Hybrid-ADS-Sperre.
- 11 Loader-Szenarien erfolgreich: hybrid_ads_wiring, aim_origin_wiring,
  shop_pre_restore, respawn_wiring, desync_repair, toggle_repair, from_sdkmod,
  unreviewed, reviewed_omni_on, reviewed_omni_off, toggle_cycle.
  Native Speicher-Fehler in den Loader-Substituten sind erwartete Ablehnungen:
  der Harness stellt keinen Windows-Spielprozess bereit.
- 6 ergänzende Übergangsprüfungen mit vorhandenen Messproben-Fixtures erfolgreich:
  tatsächliche Produktionsmodule für Summon/Exit, duale Veröffentlichung und
  Originalbyte-Rückbau; erster regulärer Capture-Installer während Camera-Blend
  ohne vorherige Fahr-Sitzung; 120 Idle-Updates ohne Fahrzeug-Speicherabfrage;
  Body/TurnState-Schließen bei Air-Übernahme; regulärer Lifecycle-Rebind mit
  fehlender/zurückkehrender Waffe sowie verweigerter Air-Übernahme ohne Exit-Ticket.
  SDK, Speicher und native Allokation sind dabei simuliert. Diese ergänzenden
  Fixtures liegen im bisherigen Messproben-Arbeitsstand, nicht in der SDKMOD.
- Ursprüngliche native Installer-Audits vergleichen weiterhin ihre alten
  Guard-Body-Fingerprints; nur der neue Layout-Query-Aufruf wird hierfür normalisiert.
- Alle Python-Dateien parsen; SDKMOD enthält genau einen passenden Stammordner,
  keine Bytecode-Caches; enthaltene Dateien entsprechen dem Quellpaket.

## Noch im Spiel zu prüfen

Die lokale Prüfung führt keine Unreal-Animationen oder Windows-Handoffs aus.
Erster Einstieg nach Spielstart, kombinierte Fahrzeug-Performance, Input-Rebinds,
Ausstiegsbogen und Luftrotation, Fast Travel, Feature-Toggles und andere
Fahrzeugtypen bleiben QA-Punkte. Ein ohnehin auftretender Respawn genügt.
Der Testplan steht in `TESTPLAN_0.3.9.19.md`.
