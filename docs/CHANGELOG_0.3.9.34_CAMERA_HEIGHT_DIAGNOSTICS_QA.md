# 0.3.9.34 – Camera Height Diagnostics QA

Basiert auf dem lokal gesicherten .33-Checkpoint `dc9fcd2`. Ben hat das freie
Omni-Umschauen im ersten Spieltest bestätigt. Die neue Fassung untersucht einen
weiteren Befund: sichtbarer Körper deutlich tiefer im Bild auf Geländern,
Kisten und kleinen Betonbarrieren. Möglicher Zusammenhang mit seltenem
Höhenversatz beim Ground-Slam-Start; IK als Ursache bislang unbestätigt.

## Sammler

`camera_height_capture.py`: nur manuell per `bl4tps_height arm <label>` und F10.
600 bestehende Widget-POST-Updates; danach automatische Abmeldung und Datei.
Registrierung erfolgt erst beim F10-Start. Keine regelmäßige Arbeit im Idle,
keine native Speicherabfrage und keine Kamera-, Mesh-, Animations- oder
Bewegungsschreibzugriffe. F10 mit laufendem Sammler stoppt und speichert.
Shutdown entfernt die Subscription vor dem bestehenden Update-Produzenten.

Zentrale Felder pro Update:

- Actor-Position/-Rotation, Movement-Mode, Geschwindigkeit, Crouch/UI/Feature-Flags.
- `Spine3`, Mesh-Weltposition, relative Mesh-Position/-Rotation; weitere geprüfte,
  tatsächlich vorhandene Root-/Pelvis-/Head-/Spine-/Foot-Sockets optional.
- CameraCache-POV und CameraModeState-POV getrennt: Position, Pitch/Yaw/Roll, FOV.
- Kamera-Getter-Position, Kollisions-/Blend-Flags, konfigurierter und angewandter Offset.
- Capsule-Position/-Halbhöhe/-Unterkante und CurrentFloor-Distanzen/Impact optional.
- Motion-Camera-Zustand mit Baseline und Filter, Parameter, Mantle-Zustand.
- Bestehende Ground-Slam-Referenzhöhen und Positions-/Handoff-Schreibzähler,
  als Kopie der vorhandenen Diagnose; der Sammler selbst schreibt keine Spielwerte.
- Relative Z-Abstände: Spine–Actor, Mesh–Actor, Camera–Actor, Camera–Spine,
  Motion-Baseline-Z und Motion-Filter-Z. Zusammenfassung gesamt und letzte 120 Updates.

Optionalfelder dürfen fehlen, ohne die Kernaufnahme zu stoppen. Keine angenommenen
Offsets oder Fallback-RVAs. Weak-Referenzen, Adressen, aktuelle Local-Runtime und
Mesh-/Movement-Zugehörigkeit werden geprüft. Owner-Wechsel vor den Kernabfragen
stoppt sofort; Prüfung am Ende verwirft eine durch synchrones SDK-Reentry
ungültig gewordene Teilaufnahme. Ein Thread-Fehler verhindert Unreal-Zugriffe.

Reads erfolgen nacheinander im Widget-POST. CameraCache, SDK-POV und Bones können
verschiedene Auswertungsphasen zeigen. Die JSON ist kein Nachweis einer atomaren
Animation-/Kamera-/Render-Aufnahme und alleine kein endgültiger IK-Beweis.
Die Kosten des Lesens sind je Update enthalten; es ist keine FPS-Messung.

Bei Abmeldefehlern bleibt die Diagnose zur Wiederholung von `off` erhalten.
Bei Dateifehlern wird `OUTPUT_FAILED` gemeldet; eine bereits entfernte
Subscription hält deswegen den Kamera-Shutdown nicht auf.

Die neuen Console-Entry-Points unterliegen dem bestehenden Build-Gate. Alle
Native-Bytes, Kamera-Verhaltensmodule, Omni-Free-Look- und Fahrzeugkorrekturen
sind gegenüber .33 unverändert. Dies ist eine Diagnosefassung ohne Höhenfix.
