# 0.3.9.40 – Ground Slam Root Exit QA

Basis .39 mit standalone Exit-Diagnose (`29f819e`). Nutzer bestätigt korrektes
Heading beim Start und Luft-Slam, aber sichtbaren Ausrichtungskonflikt beim Exit.

## Messung

`ground_slam_exit_20261012_014014_856254.json` im Nutzer-ZIP:
626 Updates, 755 native Anforderungen, keine Fehler oder optionalen Fehler,
bestätigte Bereinigung. 626 TurnState- und 129 andere Bewegungsanforderungen.

Slam beginnt bei Update 90 / 1578.94 ms, Exit bei 165 / 2866.59 ms, eigene
TPS-Rückkehr bei 248 / 4261.06 ms, ruhige TPS bei 283 / 4847.29 ms.
Actor-Yaw und Mesh-Yaw bleiben vom Slam-Start durch Rückkehr auf 105.101312°.
Alle 83 Exit-Beobachtungen zeigen Gates (1,1,0,0,0,0) und aktiven Heading-Hold.
Die sonstigen Bewegungsanforderungen ändern die Komponentenrotation nicht.

Die Root hat zu Beginn des Exits nahezu denselben Yaw wie Actor/Mesh. Ab Update
168 steigt der IdleRoot-Dispatch-Zähler, ohne Bypass; ihre relative Drehung
läuft 1.77°, 2.84°, 19.63°, -31.87°, 54.54°, -77.13°, 113.70° und schließlich
162.34°. Root-Pitch bleibt in diesem Abschnitt nahezu horizontal, daher handelt
es sich nicht um die zuvor markierte Euler-Yaw-Mehrdeutigkeit vertikaler Bones.
Später bleibt die relative Root-Drehung ungefähr 105° bis zur TPS-Rückkehr;
nach normalem Omni-Resume kehrt sie nahe null zurück. AimEnableAlpha bleibt null.

Das belegt gehaltenes Actor-/Mesh-Heading und eine stark veränderte animierte
Root. Der zeitliche Zusammenhang mit dem freigegebenen IdleTurns-Dispatch sowie
die bestehende Root-Guard-Korrektur begründen den nächsten gezielten QA-Eingriff;
die Diagnose beweist nicht jede native Instruktion oder gerenderte Pose.

## Änderung

Nur nach dem Slam, beim GroundSlamExit und dessen bereits eigenem TPS-Blend,
publiziert der finale Slam-Pfad zusätzlich `ScopedIdleRoot.control[0]=1`.
Dieser bereits installierte und auditierte Guard setzt nach der nativen Basis-
Pose-Auswertung an und überspringt nur die extra Root-Quaternion-Multiplikation
für die fünf reflektierten lokalen IdleTurns-Receiver. Die geprüfte Basis-Pose-
Callsite und nativen Ziele bleiben unverändert.

IdleUpdate bleibt 0; die Idle-State-/Pose-Auswertung wird nicht auf Idle 0
umgeschaltet. Aim und CrouchAim bleiben 0. Auch Jump-Idle/Lean und gewöhnliche
Omni-Luft-Actor-Ausrichtung bleiben für den Slam freigegeben/pausiert wie in .39.
Der bestätigte TurnState-Heading-Hold bleibt aktiv. Erwartete Gates:
Luft (1,1,0,0,0,0), Exit/eigene Rückkehr (1,1,1,0,0,0).

Die Root-Zuständigkeit wird erst beim Exit erworben; ein bloßer Luft-/TPS-Blend
aktiviert sie nicht. Ein erneuter aktiver Slam gibt sie sofort wieder frei.
Bei Combat/ADS/UI/Fahrzeug/Shop/Leiter/Slide/fremdem Modus wird sie zusammen mit
dem Heading freigegeben. Vor normalem Omni-Publish werden eigene Holds beendet,
sodass die reguläre Pipeline ihre eigenen Gates korrekt übernehmen kann.
Der Root-Guard wird beim Erwerb zusätzlich validiert; fehlende/geänderte Owner
publizieren keinen Hold. Report: `root_correction_skipped`. Shutdown schließt
Kontrollen und beide Zuständigkeitsflags.

Native Templates, Fingerprints und Receiver-Scope bleiben bytegleich; kein neuer
Patch, Hook, Producer oder Timer, keine neue gewöhnliche Omni-SDK-Abfrage.
Ground-Slam-Distanz 150 cm, Zeitquelle und akzeptierte Root-Höhen-Kamerakorrektur
bleiben bytegleich. Die Exit-/Facing-Proben akzeptieren jetzt auch .40.

Im Spiel ausstehend: sichtbare Ruhe zusammen mit der vollständigen Slam-Pose,
besonders bei gegenüberliegender Kamera; die Basis-Pose kann eigene Root-
Animation enthalten, die dieser zusätzliche Korrektur-Guard nicht unterdrückt.
