# Ground-Slam-Kameraprobe v3 für .35

Die V2-Aufnahme endete vor der ersten Exit-Zeile mit
`Exit X does not match a recent camera write owned by this probe`.
Es gab 150 SDK-Kameraänderungen, aber null Exit-Controländerungen.
Cleanup war vollständig. Der Nutzer hat folglich keine laufende V2-Rückführung
beurteilt. Der tatsächliche native Zielwert fehlte im Fehlerbericht.

## V3

Der Schutz des bestehenden nativen Exit-Targets bleibt bestehen. V3 hält bis
zu 1.024 statt 64 echte Kamera-Schreibwerte des aktuellen Slams vor, damit auch
früher erfasste Eintrittswerte vergleichbar bleiben. Neue Slams beginnen eine
neue Historie. Vor dem Abgleich werden native Zielwerte, aktueller SDK-Offset,
Anzahl, erste und letzte Kamera-Schreibwerte in `exit_diagnostics` kopiert.

Bei eindeutigem Abgleich läuft die bereits geprüfte X-Rückführung innerhalb
des vorhandenen Exit-Pfads. Ohne eindeutigen Abgleich wird der native Wert
nicht verändert. Die Aufnahme bleibt aktiv und hält den Zusatzabstand während
Exit. Beim ersten normalen TPS-Write bleibt dieser Abstand erhalten; danach
blendet der normale SDK-Setter ihn mit Zeitkonstante 0,10 s aus. Auch die
legitime TPS-Kamerablende erhält diesen Anteil. Andere Modi, FPS, ADS, UI und
ungültige Owner erhalten ihn nicht.

Dieser Ersatzpfad verschiebt die Rückkehr bis zum TPS-Wechsel. Er ist bewusst
ein Test der weichen Übergabe, noch keine Bestätigung der gewünschten
Rückführung direkt beim Aufschlag. `tps_handoff_fallbacks`, `phase` und
`exit_bridge_status` zeigen, welcher Pfad tatsächlich lief. Die Diagnosewerte
sollen den unklaren Snapshot anschließend gezielt auflösen. Kein unbekannter
nativer Zielwert wird geschätzt oder durch eine größere Toleranz zugelassen.

## Testablauf

1. V2 beendet lassen. Die bereitgestellte V2-JSON bestätigt vollständig
   aufgeräumte Hooks und den wiederhergestellten ursprünglichen Setter.
2. Weiter .35 verwenden. `ground_slam_distance_test_v3.py` nach `sdk_mods` kopieren.
3. In geladenem TPS `pyexec ground_slam_distance_test_v3.py` ausführen, F1 schließen.
4. Einen langen Slam ausführen. Sowohl Aufschlag als auch spätere TPS-Rückkehr
   beobachten; danach drei bis fünf Sekunden warten.
5. Erneut derselbe Befehl oder F10: Stop/Restore und JSON.
6. `ground_slam_distance_test_v3_<UTC>.json` aus
   `sdk_mods/settings/BL4ThirdPersonPOC_reports` und visuellen Eindruck zurückgeben.

Andere Proben vorher beenden. Sicherheitsgrenze weiterhin 180 Sekunden oder
16.000 Updates. FOV, Profilwerte, Actor/Animation, Body-Follow, Y/Z und bestehende
native Codepatches werden nicht geändert. Die temporären Kamera-/Controlwrites
sind in der JSON ausgewiesen; dies ist keine FPS-Messung.

## Lokale Prüfung

`python tests/ground_slam_distance_v3_test_scenario.py`: 20 Tests mit echtem
Loader/Router und SDK-Stubs, einschließlich der Schutz-/Restore-Prüfungen von
V2. Neue Fälle: unveränderter nicht zuordenbarer Native-Target bei aktiver
Aufnahme, vollständige Diagnosewerte, stetiges Ausblenden beim TPS-Wechsel
auch während Transition, erster TPS-Write ohne Distanzsprung, FPS-/ADS-Sperre
und ein erfasster Eintrittswert außerhalb des bisherigen 64er-Fensters.
Visuelle Render-Übergabe und native Snapshot-Bedeutung bleiben Ingame zu prüfen.
