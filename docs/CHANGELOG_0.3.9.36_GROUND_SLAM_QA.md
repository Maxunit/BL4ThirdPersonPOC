# 0.3.9.36 – Ground Slam QA

Basis: .35 Root Height QA und lokaler V4-Probenstand `4a4e316`.

## Oberkörper

Der bisherige freie Omni-Luftpfad neutralisierte weiterhin Aim-Yaw (Modus 1),
obwohl der Winkel-Fade aus .33 nur am Boden wirkte. Der native Slam-Getter
trennt nun den Slam von gewöhnlichen Sprüngen. Pro Omni-Callback wird dieser
Getter im normalen Falling-Modus höchstens einmal gelesen, am Boden gar nicht.
Aktiver Slam und GroundSlamExit schließen beide Aim-Eingriffsgates (Standing
und Crouch), bevor und nach der bestehenden Bewegungspipeline. Dabei bleiben
alle nativen Prefixes und deren exakte Receiver-/Caller-Filter bytegleich.

Im Luft-Slam dürfen auch die originale Lean-Pose und Jump-Idle-Anteile wirken;
eigene frühere Lean-/Idle-Eingriffe werden freigegeben. Omni-Richtungssteuerung
und die bestehende GroundSlamExit-Körperausrichtung bleiben erhalten.
Nach der Übergabe an normalen TPS übernimmt der übliche Bodenpfad erneut
die getestete Oberkörperbegrenzung. Sichtbarer Erfolg noch nicht live geprüft.

## Distanz

Die vom Nutzer in V4 bestätigte Funktion läuft nun im vorhandenen Kamera-
Update und scoped Offset-Setter. Kein Probe-Wrapper und keine fortlaufende
Diagnoseaufnahme. Standard 150 cm; persistenter Menüregler unter CAMERA,
0–250 cm in 5-cm-Schritten, 0 deaktiviert den Zusatz. Kamera-Reset setzt 150;
ADS-Reset verändert diese Option nicht. Der TPS-Ground-Slam-Schalter bleibt
übergeordnet.

Zwei Traces kalibrieren einmal pro schwach gebundener Runtime auf begehbarem
Boden. Ein Trace pro aktivem Slam-Update misst den Abstand der Kapselunterkante
zum Boden. Smoothstep-Rückfahrt zwischen 12 m und 1 m Kontaktreserve, mit
einem Update Vorgriff aus der Sinkgeschwindigkeit; keine feste Slam-Dauer.
Kurze Slams zoomen weniger heraus. Nach Beginn der Rückfahrt wird im selben
Slam nicht erneut herausgezoomt, auch bei vorübergehend fehlendem Trace.

Root-/Motion-/Shoulder-Anteile laufen zuerst; der Zusatz verändert nur X.
Die .35-Höhenkorrektur und der bestätigte GroundSlamExit-Landeeindruck bleiben
enthalten. Der vorhandene native Exit-Verbraucher erhält nur eine anhand
eigener SDK-Schreibwerte und gemessener Komposition bewiesene X-Korrektur.
SHA-256, Control-Layout und schwache Laufzeitbesitzer werden geprüft; fremde
Werte bleiben unangetastet. Unzuordenbare Targets verwenden die getestete
spätere TPS-Rückfahrt aus V3. Bei fehlender Bodenmessung vor der Rückfahrt
kann auch der Exit-Fallback später zurückfahren; Terrain-QA bleibt nötig.

Distance-Shutdown erfolgt vor dem GroundSlam-Native-Shutdown. Unvollständige
Restaurierung behält die abhängige Kamera-Gruppe. Es gibt keinen neuen
Update-Produzenten, Timer, nativen Code-Patch oder Animations-Worker-Callback.
