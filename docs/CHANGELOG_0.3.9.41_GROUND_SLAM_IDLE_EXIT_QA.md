# 0.3.9.41 – Ground Slam Idle Exit QA

Basis .40 mit IdleInputs-Diagnose (`4f12447`). .40 erzeugt weiterhin starkes
Oberkörperzucken trotz gehaltenem Heading und unterbundener extra Root-Korrektur.

## Belege und Grenzen

`ground_slam_idle_inputs_20261012_021945_582831.json`: 811 Updates, 255 native
Anforderungen, keine Fehler/optionalen Fehler, Cleanup vollständig. Ein Slam,
Kamera gegenüberliegend (ungefähr -180°), keine seitliche Vergleichsaufnahme.
Slam ab Update 88; Exit 156–236, eigene TPS-Rückkehr 237–270.
Actor und Mesh bleiben bei 118.270067°; Root relativ zum Actor innerhalb
ungefähr -0.00034°..0.000005° im Exit. Alle Exit-Gates (1,1,1,0,0,0).
Root-Dispatch/BYPASS-Delta jeweils 78; IdleUpdate-Dispatch-Delta 78 ohne Bypass.
Aim-Yaw wechselt zwischen den 81 Exit-Beobachtungen 80-mal das Vorzeichen,
ungefähr +177°/-177°. Spine/Head-Pose schwankt synchron. Das zeigt kein verlorenes
Root-Hold, sondern verbleibende Oberkörper-/Auswahlbewegung.

Alle fünf IdleTurns-Structs binden korrekt, aber keine scalaren Laufzeiteingaben
sind SDK-reflektiert. Sichtbar sind nur Idle/LeftTurn/RightTurn/TurnToIdle/
IdleToTurn-Verknüpfungen. Die Code-Kopie wurde vollständig erfasst.

Im originalen Update ab RVA 0x186e850 normalisiert der aktive Zweig Winkel-
Differenzen und wählt anhand eines Vorzeichens Eingangsindex 1/2 samt Position
im passenden Player. Der vorhandene Fallback bei 0x186e899 wählt Index 0,
danach bleibt der normale generische Update-Aufruf bei 0x186e911 erhalten.
Die Live-Privatwerte/gewählten Indizes sind in dieser Aufnahme nicht enthalten:
Aim-Yaw ist kein Beweis, dass genau dieser private Delta bei jedem Call wechselt.
Der Zusammenhang begründet eine gezielte QA, keine bestätigte Render-Ursache.

## Änderung

Zusätzlich zu .40 publiziert der finale Exit-Pfad das vorhandene lokal begrenzte
ScopedIdleUpdate-Gate. Es wählt den originalen Idle-Fallback vor der Drehpose-
Auswahl; es entfernt keinen generischen Update-Aufruf. Root- und Heading-Hold
bleiben. Aim/CrouchAim werden dabei nie wieder geöffnet, auch nicht zwischen
SDK-Abfragen. Dies unterscheidet sich vom alten .37-Pfad, der Standing-Aim
zwischenzeitlich aktivierte und noch den gewöhnlichen Luft-Pfad nutzte.

Nur Exit und dessen eigene TPS-Rückkehr: Gates (1,1,1,1,0,0). In der Luft bleiben
Root/IdleUpdate/Aim nativ: (1,1,0,0,0,0). Eigene Idle-Zuständigkeit wird bei neuer
Luftphase, Sonderpriorität, normalem Resume und Shutdown geschlossen. Normaler
Omni kann seinen eigenen Idle-Guard danach übernehmen. Fehlender/geänderter
Idle-Guard verhindert eine partielle Publikation. Report: idle_fallback_selected.

Die native Auswahl wurde mit dem exakt erfassten, hash-geprüften Update und dem
unveränderten Prefix ausgeführt: synthetische Win64-ABI-Nodes/Helper, kontrollierte
private Werte/Konstanten, alle externen Calls/RIP-Ziele in lokale Testziele
relokiert. +/-177° liefert nativ 2/1, der eigene Guard 0/0, fremde Nodes 2/1;
der generische Update-Helper wird in jedem Fall einmal aufgerufen. Das beweist
Dispatch-Semantik im Harness, keine vollständige Unreal-Graph- oder Slam-Pose.

Keine neuen nativen Templates, Fingerprints, ausführbaren Patches, Hooks,
Producer oder Timer; keine neuen gewöhnlichen Omni-SDK-Getter. Distanz mit 150 cm,
Zeitquelle und Root-Höhenkorrektur bleiben bytegleich zu .40.

Diagnoseproben akzeptieren jetzt .41. IdleInputs hat einen optionalen, ausschließlich
beim exakten erfassten Code-Hash erlaubten privaten Scalar-Reader für dieselben
validierten fünf Receiver. Es folgt keinen privaten Pointern und schreibt keine
Felder; dies dient nur einem verbleibenden Fehler, nicht normalem Mod-Betrieb.

Spiel-QA ausstehend: verschwindet der sichtbare Wechsel, bleibt die gesamte
Slam-/Exit-Animation erhalten? Die Wahl von Idle 0 kann native Pose-Links ändern;
keine Behauptung, dass der Harness diese sichtbare Eigenschaft verifiziert hat.
