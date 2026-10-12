# 0.3.9.39 – Ground Slam Heading QA

Basis .38 einschließlich beider standalone Diagnoseproben (`8e4cfb0`).
Der Nutzer bestätigt die vollständige Slam-Animation in .38, aber die Figur
dreht sich zur Kamera. Die erste Facing-Aufzeichnung lokalisiert die Änderung
in der Luft: Actor, Mesh und Root drehen gemeinsam, Kamera bleibt stehen.

Die zweite Aufzeichnung `ground_slam_rotation_20261012_003903_341955.json`
enthält 572 Updates, 203 native Anforderungen, keine Fehler und bestätigte
Bereinigung. Return-RVAs: 79 × `0x2e2e17` (bekannter TurnState),
124 × `0x2eec48` (anderer Bewegungsaufruf).

- Update 78: nativer Slam aktiv, Actor-Yaw noch 112.451322°, alle sechs
  Omni-Verhaltensgates geschlossen.
- Vor Update 79: Record 123 (`0x2eec48`) fordert den aktuellen Yaw ohne
  Richtungsänderung an. Record 124 (`0x2e2e17`) fordert -100.914978° statt
  112.451322° an; kleinster Winkelunterschied +146.633700°.
- Update 79: Actor-Yaw ist -100.914978°. Spätere Bewegungsaufrufe übernehmen
  diesen Yaw. GroundSlamExit beginnt erst bei Update 153.

Das grenzt den gemessenen Richtungswechsel auf den bereits bewachten
TurnState-Callsite ein. Eine Anforderung beweist allein nicht die Ausführung;
die Übereinstimmung mit dem anschließenden Actor-Yaw stützt diese Zuordnung.
Der Recorder erfasst weder andere Dispatch-Pfade noch gerenderte Pose-Details.

.39 publiziert nach der vorhandenen Special-Pipeline ausschließlich Turn und
TurnReplace für diesen exakten Callsite. Der bestehende native Prefix reicht
die aktuelle UpdatedComponent-Quaternion statt der angeforderten Quaternion
weiter. Movement-, Thread-, UpdatedComponent-, Build- und Caller-Guards bleiben
unverändert. Kein neuer Maschinencode, kein Actor-Setter, keine gespeicherte
Ausrichtung und keine zusätzlichen SDK-Getter im normalen Omni-Pfad.

Aim, CrouchAim, IdleRoot, IdleUpdate und Jump-Idle bleiben im Slam freigegeben.
Die gewöhnliche Omni-Luftausrichtung bleibt während des Slams pausiert. Der
Heading-Hold reicht über Exit und den eigenen TPS-Blend; bei ruhiger Rückkehr
wird er vor normaler Omni-Publikation geschlossen. Combat/ADS/UI/Fahrzeuge/
Shop/Leiter/Slide sowie fremde Kameramodi sind ausgeschlossen. Die bestehende
Release-Barriere und das vollständige native Cleanup bleiben erhalten.

Der Heading-Guard wird beim Erwerb zusätzlich validiert; danach gelten die
vorhandenen gestaffelten Owner-Audits. Ein nicht freigegebenes Pose-Gate oder
fehlender nativer Guard löst die vorhandene sichere Fehlerbereinigung aus.
Ein kompakter Report `ground_slam_heading_hold` zeigt die Zuständigkeit.

Die Facing-Probe akzeptiert jetzt .38/.39; die .38-Rotation-Probe bleibt bewusst
.38-only. Ground-Slam-Distanz (150 cm), Zeitquelle, Root-Höhe und alle nativen
Templates bleiben bytegleich. Vollständige Animation und gehaltene Richtung
zusammen sind noch im Spiel zu bestätigen.
