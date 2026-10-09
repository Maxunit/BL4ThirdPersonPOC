# 0.3.9.15 – QA: gehaltenes TPS-ADS beim Scope-Rückweg

Basis: QA-Build 0.3.9.14 auf GitHub-Commit
`22c613606548ce62c27a289f02ebc1e17a308b24` (0.3.9.13).

## Befund aus dem Spieltest

QA bestätigt funktionierende Wechsel zwischen TPS-ADS und FPS-ADS. Der Bericht
`player_omnidirectional_snapshot_20261009_155431_227114.json` enthält acht
Scope-Tastendrücke, 198 Updates in der Scope-Pause, `status=RUNNING` und keine
Supervisor- oder Gameplay-Fehler. Die Übergabe aus .14 funktioniert in diesem
Lauf ohne die vorherige Omni-Schutzabschaltung.

Bei Shift aus FPS-ADS zurück zum gehaltenen TPS-ADS beobachtet QA dagegen
kurz einen vollständigen Zoom-Reset. Der .14-Code kehrte zunächst ohne
TPS-ADS-Zustand zurück, wartete auf das Ende des nativen Kamera-Blends und
startete danach einen neuen `zoom_in`. Auch der Rückweg des Kamera-Offsets
zielte zunächst auf Hüftposition statt auf die ADS-Annäherung. Das erklärt
einen zweistufigen Rückweg; die native FOV-Kurve war im alten Report nicht
aufgezeichnet und ist dadurch noch nicht numerisch belegt.

## Gezielte Änderung

- Beim Eintritt in den Scope bleiben TPS-Basis-FOV, Ziel-FOV und ursprünglicher
  FOV-Offset als skalare Werte erhalten. Controller, Pawn, Kamera und Waffe
  sind durch WeakPointer gebunden. Der neue Zwischenspeicher hält keinen
  geliehenen `CameraModeState`-Struct.
- Nach einem beobachteten Wechsel auf `ThirdPerson` bekommt das TPS-Ziel
  während des vorhandenen nativen Blends direkt den gehaltenen ADS-Offset.
  In weiterhin gemeldetem `Default` wird dieser TPS-Offset nicht angewendet.
- Der Offset-Rückweg endet bei weiterhin gehaltenem ADS an der
  Schulterzielposition einschließlich der ADS-Annäherung. Loslassen zielt
  weiterhin auf Hüftposition.
- Erst nach Ende des beobachteten nativen Blends wird die ADS-Route wieder
  TPS. Derselbe Hold verwendet seine erhaltene TPS-Kalibrierung und setzt
  den aktuellen Ziel-FOV direkt; er beginnt keinen zweiten `zoom_in`.
  Ein neu gedrücktes ADS behält seinen normalen Zoom-Einstieg. Bestehende
  Reticle-Publikation und Same-Weapon-Rearm bleiben erhalten.
- Loslassen, Abbruch, Reset oder eine andere Waffe entfernen den Rückweg-
  Offset, soweit er noch der ursprünglichen Kamera und dieser Änderung
  gehört. Eine neue Kamera oder ein fremd überschriebenes Offset wird dabei
  nicht beschrieben. Eine auslaufende Scope-Eintrittsblende beschreibt nach
  einem Kamera-Owner-Wechsel ebenfalls keinen alten Manager mehr.
- Der Omni-Report enthält bis zu 256 `hybrid_fov_events` mit beobachtetem
  POV-FOV, FOV-Offset, Kamera-Modus, Blend-Zustand und ADS-Übergang. Fehler
  beim optionalen Lesen dieser Belege werden gezählt und stoppen Gameplay
  nicht. Dafür muss `diag` nicht eingeschaltet sein.

Keine neuen Hooks, nativen Codeänderungen oder Synchronisationsfristen.
Der vorhandene visuelle Kamera-Blend von 0,2 s bleibt bestehen.

## Prüfung und Grenzen

268 Tests unter Python 3.12.14: 264 erfolgreich, 4 plattformbedingte Skips.
15 neue Tests verbinden den ADS-Aufbau und die Routen-Reconciliation mit dem
.14-Gameplay-Harness und simulierten SDK-Kameras. Geprüft sind gehaltenes
Rückweg-Ziel, fehlender zweiter Zoom-Einstieg, frisches ADS, ADS-Annäherung,
Loslassen, Waffen- und Kamerawechsel, ignorierter Kamerawechsel, fremder
Offset, Reset, Struct-Wechsel, wiederholte Wechsel und begrenzte Diagnose.
Vorhandene Loader-Szenarien und der Paket-Smoke-Test laufen in derselben Suite.

Diese Tests belegen die Python-Zustände und angeforderten Kamera-Werte.
.15 bleibt eine QA-Build; der erste bestätigte Spielablauf steht unten.
Throwable-, Beam-, Sprint-Fire- und andere Audit-Punkte sind durch diesen
Schritt nicht zusätzlich live bestätigt.

## Erster Spieltest am 09.10.2026

QA bemerkt keinen Zoom-Aussetzer mehr. Der Bericht
`player_omnidirectional_snapshot_20261009_162002_383692.json` zeigt sechs
Scope-Eintritte und sechs vollständig übernommene gehaltene TPS-Rückwege.
Die 72 `RETURN_TARGET`-Zeilen halten den Offset bei ca. −23,33° und zeigen
pro Rückweg einen nicht abnehmenden POV-FOV von ca. 16,26° bis zum TPS-Ziel
von 66,67°. Es gibt in diesen aufgezeichneten Rückwegen keinen Ausflug zur
90°-Hüft-FOV. Alle sechs `TPS_HOLD_RESUMED`-Zeilen haben `base_fov=90`,
`target_fov=66,67`, den Ziel-POV-FOV, `transitioning=false` und keinen neuen
ADS-Übergang.

Supervisor bleibt `RUNNING`, Supervisor- und Gameplay-Fehlerlisten sind leer;
keine Gameplay-Sitzung wurde beendet. Der Report hat 13 Scope-Tastendrücke
und als letztes Ergebnis `refused:not_holding_tps_ads`: eine abgelehnte
Anfrage ohne gültiges gehaltenes TPS-ADS, keine Schutzabschaltung.
Es sind keine FOV-Diagnose-Lesefehler gemeldet.

Live bestätigt ist damit der aufgezeichnete gehaltene Rückweg über
`sniper_fps` für diesen Lauf. Der Report enthält keine `RETURN_CANCELLED`-
Zeile; daraus folgt keine eigenständige Bestätigung für Loslassen während
der Rückkehr, Waffen-/Kamerawechsel oder alle anderen Waffen.
