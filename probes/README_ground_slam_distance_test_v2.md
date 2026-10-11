# Ground-Slam-Kameraprobe v2 für .35

## Anlass

Die Ingame-Aufnahme der ersten Kameraprobe enthält beim Slam X=-291 statt
des normalen X=-211 (80 cm zusätzlicher Abstand). `GroundSlamExit` hält X=-291
über etwa 1,4 Sekunden fest, obwohl die Python-Probe bereits extra=0 meldet.
Beim TPS-Wechsel verschwindet dieser Abstand in einem Schritt. Das erklärt
den gemeldeten sichtbaren Ruck und zeigt, dass die erste Übergabe unvollständig
war. Die Aufnahme selbst ist sauber: keine Fehler, Cleanup vollständig.

Der bereits vorhandene .35-Exit-Kamerapfad speichert den fertig zusammengesetzten
TPS-Offset und verwendet diesen Snapshot für seine Exit-Frames und die erste
Rückkehrabfrage. Ein ausschließlich normaler TPS-Setter kann ihn nicht ausblenden.
Außerdem können Y/Z dieses Snapshots vom letzten direkten Probenwert abweichen;
deshalb durfte die bisherige vollständige Vektor-Wiederherstellung ihn nicht ändern.

## Änderung

v2 fährt ausschließlich den nachweislich von der Probe hinzugefügten X-Abstand
im vorhandenen Exit-Kamerapfad zurück. Ziel ist der erfasste native X-Offset
plus genau der ursprüngliche Probenanteil. Übergang: exponentielle Reaktion
mit Zeitkonstante 0,10 s, ungefähr 95 Prozent Abbau nach 0,30 s. Dadurch ist der
Abstand normalerweise schon während GroundSlamExit neutral, bevor TPS zurückkehrt.
Der Beginn bleibt bei maximal 80 cm Zusatzabstand und Zeitkonstante 0,08 s.

Y/Z, Körperanker, Bone-Follow, Rotation, FOV, Kameraprofile und die bestehenden
native Hook-/Blend-Funktionen bleiben unverändert. Die visuelle Wirkung und
das erhaltene „Oomph“ müssen weiterhin Ingame bewertet werden.

Die Schnittstelle verwendet genau den bereits gepinnten Python-Controlbuffer
des .35-Exit-Owners: nur dessen X-Double bei Offset 160. Keine neue Speicheradresse
im Spiel wird gelesen/beschrieben; keine neue Code-Patch- oder DLL-Installation.
Der vorhandene, bereits abgesicherte native Consumer liest den geänderten Zielwert.
Dies ist ein schreibender Test und keine reine SDK-Leseprobe.

Vor jedem Zugriff werden GameThread, Mod-/Owner-Zugehörigkeit, serialisierte
Runtime-Referenzen, Controlbuffer-Größe 256 und Ausrichtung, aktive/initialisierte
Flags sowie der geprüfte Offset-Consumer-Fingerprint validiert. Das native X
muss genau einem der letzten 64 tatsächlich von dieser Probe geschriebenen
X-Werte entsprechen; dadurch wird kein Abstand geschätzt oder aus Profilwerten
geraten. Alle Ziele bleiben endlich und innerhalb der bestehenden Exit-Grenze 512.
Ein fremder Controlwriter, unpassender Fingerprint oder Ownerwechsel bricht ab.
Cleanup stellt nur den eigenen, noch übereinstimmenden Beitrag wieder her.
`exit_control_writes` weist die Controländerungen getrennt von SDK-Kamerawrites aus.

## Test

1. Erste Probe mit demselben alten PyExec-Befehl oder F10 beenden.
2. `ground_slam_distance_test_v2.py` nach `sdk_mods` kopieren.
3. In geladenem TPS `pyexec ground_slam_distance_test_v2.py` ausführen und F1 schließen.
4. Normalen Sprung, langen Slam und (nach vollständig beruhigter Kamera) kurzen
   Slam testen. Den Übergang direkt nach dem Aufschlag und die spätere TPS-Rückkehr
   beobachten. Auch beurteilen, ob die angenehme Höhenbewegung erhalten bleibt.
5. Nach Rückkehr drei bis fünf Sekunden warten. Derselbe Befehl oder F10 stoppt
   und stellt den ursprünglichen Python-Setter sowie den eigenen Exit-Anteil wieder her.
6. `ground_slam_distance_test_v2_<UTC>.json` aus
   `sdk_mods/settings/BL4ThirdPersonPOC_reports` zurückgeben; `RESTORED` nennt den Pfad.

Weiterhin .35 verwenden. Keine weiteren Kameraproben oder Omni-Profiler parallel.
Sicherheitsgrenze: 180 Sekunden einschließlich Startwartezeit oder 16.000 Updates.

## Lokale Prüfung

`python tests/ground_slam_distance_v2_test_scenario.py`: 17 lokale Tests auf
echtem Loader/Update-Router mit simulierten SDK-/Runtime-Objekten und einem
realen ctypes-Controlbuffer. Darunter die v1-Aufnahme nachgestellt (gefrorenes X,
abweichendes Y/Z), stetige Rückführung von X, erhaltenes Y/Z, Stop während Exit,
realer .35-Setter mit Root-Korrektur, unveränderte normale Sprünge, Cleanup,
Owner-/Fingerprint-/Zielabgleich und vergleichbare Interpolation bei verschiedenen
Updatefrequenzen. Kein Ersatz für einen Ingame-Nachweis der Render-Übergabe.
