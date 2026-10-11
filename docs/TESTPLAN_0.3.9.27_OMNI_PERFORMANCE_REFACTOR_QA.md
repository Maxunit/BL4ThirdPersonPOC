# 0.3.9.27 – Vergleich mit .26 und Gameplay-QA

Spiel vollständig beenden; alte Mod-Dateien und PyCache entfernen.
Eine Variante installieren: `dist/BL4ThirdPersonPOC.sdkmod` oder den Quellordner.
Grafik, DLSS, FrameGen und das bestehende 120-FPS-Limit beibehalten.

## Gleicher Idle-Vergleich

1. Dieselbe Stelle und denselben Blick wie bei den drei .26-JSONs verwenden.
   Normale TPS, UI geschlossen; `bl4tps_omni diag off`.
2. FPS mit Omni aus notieren; Omni einschalten und FPS erneut notieren.
3. `bl4tps_omni profile total idle_a`; Konsole schließen, F10, unverändert
   stehenbleiben bis zum automatischen Abschluss nach 600 Gameplay-Updates.
4. Ebenso `bl4tps_omni profile detail idle_detail` durchführen.
5. Ebenso `bl4tps_omni profile total idle_b` durchführen.

Die drei JSONs aus `sdk_mods/settings/BL4ThirdPersonPOC_reports` und die
angezeigten FPS zurückgeben. Relevant sind die Total-Messungen gegenüber
4.073605 und 4.022381 ms in .26. Detail dient der Zuordnung: `sampling.visual`
soll bei Diagnose aus entfallen; `visual.guard` bleibt vorhanden. Die Summe
kann auch durch andere verbleibende Arbeit begrenzt sein. Detail bringt selbst
Messaufwand mit und eignet sich nicht als Total-Ersatz.

F10 während eines laufenden Captures beendet ihn mit Teilbericht.
`bl4tps_omni profile stop|status` bleibt verfügbar.

## Gameplay-Regressionscheck

- WASD und vorhandene Stick-Belegung, Sprint, Ground-Dash, Jump/Air-Dash,
  Slide und Slam: Richtung, Übergabe und Rückkehr vergleichen.
- Schießen aus Sprint, Nachladen, Waffentausch, Granate und Objektwurf prüfen.
- Hold-ADS und Toggle-ADS mit Hybrid-Scope via Sprint/Shift: TPS-Reticle muss
  beim FPS-Scope verschwinden und bei Rückkehr korrekt wieder erscheinen.
- UI/Shop, Leiter, Fahrzeug ein/aus und TPS/FPS-Wechsel: keine falsche
  Steuerungsübernahme; Respawn/Mapwechsel bei Gelegenheit ebenfalls prüfen.
- Eine belegte Aktion im Menü umbelegen, zurück ins Spiel: neue Taste muss
  verwendet werden; vorhandene Release-Barrieren bleiben erhalten.
- Omni aus/an: normale Bewegung und sauberes erneutes Binden.

Optional nach dem Idle-Vergleich kurz `bl4tps_omni diag on` und laufen:
vollständige Visual-Diagnose muss verfügbar bleiben. Für Performance-Vergleiche
anschließend wieder `diag off` verwenden. Keine weiteren Hotkeys erforderlich.
