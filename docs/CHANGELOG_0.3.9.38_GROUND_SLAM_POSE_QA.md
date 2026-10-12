# 0.3.9.38 – Ground Slam Pose QA

Basis .37 (`1d27e42`). Nutzerfall: Kamera Norden, Figur Süden; beim
GroundSlamExit schnelles Zittern und unvollständige Oberkörperanimation.

Die bisherige Korrektur schloss Standing-/Crouch-Aim-Gates während des Slams.
Der ältere Exit-Pfad reaktivierte aber TurnState-Körper-Hold und beide
Idle-Eingriffe. Der lokale echte Exit-Pfad ergibt vor der Änderung Gates
(Turn, Turn-Ersatz, IdleRoot, IdleUpdate, Aim, CrouchAim) = (1,1,1,1,0,0).

.38 gibt diese gesamte Gruppe an das Spiel ab. Der Slam-Exit-Pfad aktiviert
keinen Körper-Hold und keine Idle-/Aim-Eingriffe mehr, auch nicht vorübergehend
zwischen SDK-Abfragen. Native Argumentaufzeichnung bleibt rein beobachtend.
Pose-Detailfelder werden nur bei aktiver Pose-Diagnose gelesen.

Der native Slam-Getter routet auch die Luftphase durch die vorhandene
Special-Pause. So konkurriert dort kein gewöhnlicher Omni-Luft-Actor-Setter
mit dem Slam. Vor Eintritt werden alte freie Aim-/Idle-/Turn-Gates geschlossen
und eine vorherige Jump-Idle-Episode beendet. GroundSlamExit sowie dessen
Übergang nach ThirdPerson behalten native Pose-Zuständigkeit bis der
Kamera-Blend abgeschlossen ist. Normale Sprünge und fremde TPS-Blends erhalten
diese Ausnahme nicht. Danach übernimmt die bestehende Omni-Wiederaufnahme,
einschließlich ihres Input-Release-Verhaltens.

Bewusste Ausrichtungsänderung: Während des Slams darf das Spiel die Figur
nativ ausrichten. Die QA garantiert kein Festhalten am bisherigen Actor-Yaw;
nachher geht Omni von der aktuellen Richtung aus. Der Nutzer muss beurteilen,
ob das neben der Animationsruhe auch für das Gameplay passt.

Ground-Slam-Distanz (150 cm, Menü 0–250), Widget-Zeitquelle und Root-Höhenmodul
sind bytegleich zu .37. Kein neuer Hook, Timer, Producer oder nativer Patch;
die bestehenden native Templates, Fingerprints und Cleanup-Verträge bleiben.
