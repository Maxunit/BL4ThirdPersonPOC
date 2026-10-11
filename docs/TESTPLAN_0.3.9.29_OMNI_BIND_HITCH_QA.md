# 0.3.9.29 – Testplan

Spiel vollständig beenden; alte Mod-Dateien und PyCache entfernen. Eine Variante
installieren. `bl4tps_omni diag off`.

## 1. Ruckler zuordnen (wichtigster Teil)

Bei jedem Ruckler auf die Konsole achten (oder danach `bl4tps_omni report`,
Abschnitt `hitches`). Eine Zeile sieht so aus:

    [OmniHitch] lifecycle 9.8 ms: session.install 9.5, input.mapping_scan 1.9, ...

- **Spielstand laden, dann erste Bewegung.** Erscheint eine `[OmniHitch]`-Zeile?
  Welche Schritte stehen drin (`bind.*`, `clips.ground.GetAnimationFromTag`, ...)?
- **Einsteigen und Aussteigen**, je dreimal hintereinander. Ruckelt es jedes Mal
  oder nur beim ersten Mal? Welche Zeilen erscheinen (`session.retire`,
  `session.install`, `bind.*`, `vehicle.*`)?
- **Dieselben drei Situationen einmal mit Omni aus.** Ruckelt es dann auch, kommt
  der Ruckler vom Spiel oder vom TPS-Teil der Mod, nicht von Omni.

Keine `[OmniHitch]`-Zeile während eines Rucklers heißt: Omnis Callbacks waren
nicht die Ursache. Zeilen mit `no named step` mitten im normalen Spiel sind
ebenfalls interessant (Hinweis auf Python-Speicherbereinigung oder andere
Laufzeitpausen): bitte mit ungefährer Häufigkeit notieren.

## 2. Laufen

1. Dieselbe kurze Strecke (geradeaus, dann Kurve) mit Omni **aus** laufen, FPS notieren.
2. Dieselbe Strecke mit Omni **an**.
3. Optional beim Laufen: `bl4tps_omni profile total run_a` → F10 → laufen, bis die
   600 Updates voll sind. JSON zurückgeben.

Der Abstand Omni aus/an beim Laufen ist der echte Omni-Anteil. Der Rest ist das Spiel.

## 3. Regressionscheck

- Nach dem Laden und nach dem Aussteigen: Omni übernimmt nach einem kurzen
  Moment (~0,1 s). Erste Schritte sauber?
- Sprint aus Lauf, Ground-Dash geradeaus und schräg (Forward-Clip), Jump/Air-Dash,
  Slide, Slam, Crouch.
- Schießen aus Sprint (Rückkehr in die Laufrichtung), Granate, Objektwurf.
- Hybrid-Scope per Sprint bei gehaltenem und getoggeltem ADS.
- Fahrzeug ein/aus mehrmals, Respawn, Mapwechsel, Omni aus/an.
- `bl4tps_omni report`: `errors` leer, `current_gameplay.bind_steps` zeigt die sieben Schritte.
