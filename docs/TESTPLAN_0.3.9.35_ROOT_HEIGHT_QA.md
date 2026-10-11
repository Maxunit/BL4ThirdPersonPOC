# 0.3.9.35 – kurzer Spieltest

Spiel ganz beenden. Alte Mod-Dateien und PyCache entfernen. Entweder
`dist/BL4ThirdPersonPOC.sdkmod` oder den Quellordner `BL4ThirdPersonPOC/`
installieren; nur eine Variante. Vorhandene Einstellungen werden weiterverwendet.

1. **Bekannte Boden-/Geländerstelle:** Auf dem Boden sollte die Grundhöhe passen.
   Aufs Geländer wechseln und mindestens 10 Sekunden stehen bleiben: Der Körper
   sollte seinen bisherigen Bildausschnitt ungefähr behalten; die Korrektur darf
   nicht wieder wegdriften. Heruntergehen: kein bleibender Kameraversatz.
2. **Motion an und aus:** Beide Varianten testen. Auf dem Geländer die Kamera
   nach oben/unten drehen: senkrechte Korrektur ohne zusätzlichen Abstandsschub
   oder seitliche Wanderung. Andere Kiste/Betonbarriere probieren. Auch einmal
   TPS direkt auf dem Hindernis aktivieren.
3. **Übergänge:** Laufen, Springen, Landen und Ducken; anschließend normales
   Grounded TPS. TPS-ADS/FPS-ADS/Hybrid, F5, Leiter/Mantle, Slide, Fahrzeug
   betreten/verlassen. Kein zurückbleibender Höhenzusatz. Ground Slam nur als
   Regression testen; dieser Build ist dafür kein belegter Fix.
4. **Vergleichsschalter:** CAMERA → Grounded Body Height (QA), oder
   `bl4tps_root_height off` / `on`. Für den Bildvergleich Konsole schließen.
   Im Stillstand außerdem FPS mit an/aus vergleichen, ohne aktive Diagnose.
   UFunction-Zahlen aus den lokalen Tests sind keine Performance-Messung im Spiel.

Bei auffälligem Verhalten: `bl4tps_height arm qa35_wechsel`, Konsole schließen,
F10, den kurzen Wechsel aufnehmen. Für zwei Standvergleiche Labels `qa35_boden`
und `qa35_gelaender` verwenden. Aufnahme dauert ungefähr 10 Sekunden bei 60
vorhandenen Updates pro Sekunde. JSON im bisherigen Report-Ordner; Root-Korrektur
steht unter `root_height`. Die Motion-Baseline-Z ist jetzt bei aktiver Zerlegung
Root-bereinigt, `relative.spine_actor_z` bleibt eine unveränderte Beobachtung.

Falls die neue Höhe unangenehm ist, Schalter aus: Root-Abfragen und Korrektur
entfallen, die bisherige Motion-Messweise wird wieder benutzt. Auffällige
`[BL4ThirdPersonPOC.RootHeight] DECLINED`-Meldungen bitte zusammen mit der
Aufnahme weitergeben.
