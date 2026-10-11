# BL4ThirdPersonPOC 0.3.9.29 Omni Bind & Hitch QA (Claude)

Basiert auf 0.3.9.28. Neu: ein Ruckler-Logger für Omnis eigene Callbacks
(`[OmniHitch]` in der Konsole), gestaffeltes Binden einer Session über mehrere
Updates statt in einem langen Frame, günstigeres Neu-Binden (Knochen, Schema,
Tastenscan) und ein schlankerer Laufen-Pfad (Kampf-Auswertung und Handler-Prüfung
einmal pro Update, Granaten-Scan ohne Pfadnamen).

- [Befund und Änderungen](docs/CHANGELOG_0.3.9.29_OMNI_BIND_HITCH_QA.md)
- [Testplan: Ruckler zuordnen, Laufen messen](docs/TESTPLAN_0.3.9.29_OMNI_BIND_HITCH_QA.md)
- [Lokale Validierung](docs/VALIDATION_0.3.9.29_OMNI_BIND_HITCH_QA.md)
- Vorgänger: [0.3.9.28 Callback-Scope](docs/CHANGELOG_0.3.9.28_OMNI_CALLBACK_SCOPE_QA.md)
- Zähl-Umgebung: `python tests/omni_idle_cost_scenario.py stand|crouch|move|turn --report`

Installierbar: `dist/BL4ThirdPersonPOC.sdkmod`; gleichwertiger Quellordner:
`BL4ThirdPersonPOC/`. Nur eine Variante installieren. Spiel vollständig beenden
und alte Mod-Dateien sowie ihren PyCache entfernen.

---

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
- `bl4tps_omni [on|off|status|report|diag on|off|hybrid on|off|status]`: `hybrid` schaltet den Hybrid ADS Mode (nur mit Omni) ; Zoom wird im ADS-ZOOM-Menü eingestellt
- `bl4tps_actions [all]`: listet die Spielaktionen, gleicht die Keybinds sofort ab und zeigt den Sync-Zustand
- `bl4tps_build`: zeigt den erkannten Build und das Gate
- `bl4tps_weapon_probe [live]`: misst lesend den nativen Feuer- und Zielpfad der ausgerüsteten Waffe (JSON im Report-Ordner); `live` ruft zusätzlich die beiden Ziel-Getter der Kameraverwaltung einmal auf
- `bl4tps_native_dump <rva> … [--length 0x800]`: liest nur Codefenster für die Offline-Analyse
- `bl4tps_aim [status|on|off|margin <cm>|beam_margin <cm>]`: Ziel-Trace und Beam-Abfrage starten in TPS auf Figurentiefe (Standard an, Rand und Beam-Rand je 70 cm); `status` zeigt unter `beam` die Beam-Zähler

Lokale QA-Prüfung: [VALIDATION_0.3.9.19.md](docs/VALIDATION_0.3.9.19.md).
