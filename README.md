# BL4ThirdPersonPOC – Entwicklungsstand

| Pfad | Inhalt |
|---|---|
| `BL4ThirdPersonPOC/` | Die Mod (wird zur `.sdkmod` gepackt) |
| `BL4ThirdPersonPOC/omni/` | Integriertes Omnidirectional Movement (experimentell, Standard aus) |
| `BL4ThirdPersonPOC/build_gate.py` | Zentrale Build-Erkennung (Steam/Epic, geprüfte Builds) |
| `BL4ThirdPersonPOC/input_bindings.py` | Gemeinsamer Leser der Enhanced-Input-Belegung |
| `BL4ThirdPersonPOC/action_keys.py` | ADS-/Interaktions-Keybinds folgen der Spielbelegung |
| `tests/` | Python-Tests mit SDK-Stubs, Smoke-Test der echten Mod |
| `docs/` | Changelog, Testplan, Omni-Labordoku (`docs/omni/`) |
| `tools/build_sdkmod.py` | Baut `dist/BL4ThirdPersonPOC.sdkmod` |

## Bauen und Testen
```
python tools/build_sdkmod.py
cd tests && python -m unittest discover -s . -p "test_*.py"
python docs/omni/run_idle_scope_validation.py   # nur Linux x64
```
Die Tests prüfen die Python-Logik, die Verdrahtung und das Cleanup. Sie ersetzen keinen Spieltest. Aktueller gezielter Nachtest: `docs/TESTPLAN_0.3.9.18.md` (Integration der bestätigten Granaten-Ausrichtung mit Zustandsnachlauf). Die Hybrid-/Omni-Übergabe aus .14, der gehaltene Sniper-Rückweg aus .15, der Objektwurf aus .17 und die längere Granaten-A/B-Variante wurden im Spieltest bestätigt. Weitere offene Tests stehen in `docs/TESTPLAN_0.3.9.13.md` bzw. `docs/TESTPLAN_0.3.9.12.md`; der Reparaturstand steht in `docs/FIX_TRACKER_0.3.9.13.md`.

## Konsolenbefehle (neu in 0.3.9.0)
- `bl4tps_omni [on|off|status|report|diag on|off|hybrid on|off|dolly <cm>|zoom <x>]`: `hybrid` schaltet den Hybrid ADS Mode (nur mit Omni) und stellt Kamera-Annäherung und Zoom-Deckel beim Halten ein
- `bl4tps_actions [all]`: listet die Spielaktionen, gleicht die Keybinds sofort ab und zeigt den Sync-Zustand
- `bl4tps_build`: zeigt den erkannten Build und das Gate
- `bl4tps_weapon_probe [live]`: misst lesend den nativen Feuer- und Zielpfad der ausgerüsteten Waffe (JSON im Report-Ordner); `live` ruft zusätzlich die beiden Ziel-Getter der Kameraverwaltung einmal auf
- `bl4tps_native_dump <rva> … [--length 0x800]`: liest nur Codefenster für die Offline-Analyse
- `bl4tps_aim [status|on|off|margin <cm>|beam_margin <cm>]`: Ziel-Trace und Beam-Abfrage starten in TPS auf Figurentiefe (Standard an, Rand und Beam-Rand je 70 cm); `status` zeigt unter `beam` die Beam-Zähler
