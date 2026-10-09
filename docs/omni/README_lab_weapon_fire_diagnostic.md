# BL4 Omnidirectional – Weapon Fire State Diagnostic

Basis: SprintFire Handoff Validation v2, Gameplay unverändert. Diese Build diagnostiziert den nachgewiesenen Empty-Magazine-Hänger und behebt ihn noch nicht.

Bericht193455: Ein Sprint-Fire-Versuch armiert WAIT_NATIVE_FIRE bei4.187s. Nach Loslassen bei4.278s bleibt dieser Zustand bis zum Stop bei8.955s bestehen. Keine Feuer-/Reload-Animation; WeaponState bleibt Active. Keine Fehler und vollständiges Cleanup mit0 Hooks/Patches. Die bisher beobachteten Zustände unterscheiden einen verzögerten gültigen Schuss nicht zuverlässig von einem abgelehnten Versuch.

Neue rein lesende SDK-Diagnose: weapon_fire_diagnostic sammelt reflektierte benannte Kandidaten für Ammo/Fire/Queue/Reload/WeaponState einschließlich passender Object-/Struct-Unterfelder bis Tiefe2. Keine geratenen Feldnamen, keine Getter-Aufrufe, keine neue native Hook oder Gameplay-Writes. Namen sind Kandidaten und belegen noch keine Semantik. Max96 Felder,16 Layouts,256 veränderte Zustandszeilen,16 Diagnosefehler; Weapon-Owner schwach referenziert. Diagnosefehler werden separat erfasst. Structfelder werden nur bei passenden Namen erfasst; vollständige Fire-Admissibility wird nicht behauptet.

Installation: BL4 beenden, bisherige Paketdateien durch sdk_mods ersetzen, alte __pycache__ entfernen, neu starten und TPS einschalten. Start/Stop: pyexec player_omnidirectional_gameplay.py.

Test mit derselben Waffe: Erst Sprint + kurzer gültiger Schuss mit Munition. Danach leeres Magazin bzw. keine Munition, Sprint + Fire antippen und loslassen. Wenn die Richtung hängenbleibt, einmal nachladen oder die Waffe wechseln und danach normal bewegen. Dann stoppen und JSON senden. Falls keine Munition beschafft werden kann, zwei getrennte kurze Läufe senden. Keine zusätzlichen Hotkeys.

Der bekannte Hänger kann in dieser Diagnose weiter auftreten; manuell stoppen stellt die ursprünglichen Zustände wieder her. Keine feste Timeout-Korrektur: Ziel ist ein belegtes Ammo-/Pending-/Reject-Signal, das die erfolgreich getestete Sprint-Feuer-Übergabe erhält.

48 lokale Python-/SDK-Stub-Tests bestanden. Neue Diagnose prüft reflektierte Kandidaten, Änderungserfassung und tolerierte optionale Lesefehler. Windows-/BL4-Diagnoselayout noch unbestätigt.
