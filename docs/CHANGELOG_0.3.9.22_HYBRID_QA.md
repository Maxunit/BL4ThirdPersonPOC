# 0.3.9.22 Hybrid QA – Kamera-Lifecycle registrieren

Der gemessene Fast-Travel-Lauf aus .21 hatte keine regulären Kamera-PRE-/POST-
Hooks für ClientRestart. Der Spielaufruf erreichte die Diagnose-Hooks, während
`restart_calls` und `local_restarts` bei 0 blieben. Danach griff `tps_desync`.
Der Aktivierungslog bestätigt `ClientRestart PRE hook refused`.

- Der Installer prüft beide Registrierungen mit `has_hook`, anstatt den
  Rückgabewert von `add_hook` als alleinige Erfolgsbedingung zu verwenden.
- Hintergrund: Der untersuchte SDK-Quellpfad fügt neue Identifikatoren an eine
  bestehende Funktion/Hook-Typ-Sammlung an und erreicht danach `return false`.
  Ein vorhandener Omni-PRE-Hook kann genau diese Situation herstellen.
- Erfolgsmeldung: `CLIENT_RESTART_HOOKS_VERIFIED pre=True post=True`, mit den
  tatsächlichen `add_hook`-Rückgabewerten für die Diagnose.
- Vor einer Neuregistrierung und nach einer Entfernung werden die stabilen
  Mod-Identifikatoren geprüft. Fehlgeschlagene Bereinigung bleibt erfasst und
  verhindert die erneute Registrierung über einen noch vorhandenen Callback.
- PRE-/POST-Callback-Logik, native Eingriffe, Reparatur-Wartezeiten und
  Überblendungszeiten bleiben erhalten. Hybrid bleibt optional, Standard aus.

Enthält die .21-Dolly-Entfernung, .20-Zoom-/Waffenübergabe-Korrekturen sowie
die .19-Omni-/Fahrzeugoptimierungen. Keine neuen Timer oder Eingabebelegungen.

Die Registrierung ist lokal geprüft. Fast Travel, Save-Load und Respawn
brauchen für eine Aussage zur sichtbaren Kameraübergabe weitere Spiel-QA.

Untersuchte Primärquelle:
[unrealsdk hook_manager.cpp](https://github.com/bl-sdk/unrealsdk/blob/master/src/unrealsdk/hook_manager.cpp),
Git-Blob `382fc3c8d8024c2c8734c4d289cb7e40124213ae`.
Die Python-Bindung reicht den booleschen Rückgabewert weiter:
[pyunrealsdk hook.cpp](https://github.com/bl-sdk/pyunrealsdk/blob/master/src/pyunrealsdk/hook.cpp).
