# 0.3.9.33 – Omni Free Look QA

Ziel: Beim freien Omni-Umschauen darf die Kamera vor der Figur sein, ohne deren
Oberkörper weiterhin nach Kamera-Pitch zu neigen. Hinter der Figur darf sich der
Oberkörper wieder begrenzt seitlich mitdrehen.

## Verhalten

- Kamera-Yaw relativ zum aktuellen Actor-Yaw; Welt-Richtung und ±180°-Übergang
  beeinflussen die Grenze nicht. Vorhandene Kamera-Samples werden verwendet.
- Aim-Yaw-Eingabe maximal ±35°. Bis ±60° Kamerawinkel bleibt Pitch unverändert.
- Zwischen 60° und 90°: gemeinsames, winkelabhängiges Smoothstep-Ausblenden von
  begrenzter Drehung und Pitch. Ab 90° bis zur Frontansicht sind beide neutral.
- Die 35° begrenzen die AimOffset-Eingabe, nicht direkt den Winkel eines Bones.
  Der sichtbare Umfang und die anatomische Drehrichtung brauchen den Spieltest.
- Freies Omni am Boden, stehend oder geduckt, nach Aktivierung des Body-Follow.
  Die vorhandene Kampfentscheidung bleibt zuständig für ADS/Feuern/Werfen.
  Luft, Dash, Slide und Slide-Ausgang behalten ihre bisherige Aim-Behandlung.
- Kein zeitliches Nachlaufen: Der sanfte Übergang kommt aus dem Kamerawinkel.
  Normales TPS ohne Omni verwendet weiterhin seine Spielanimation.

## Umsetzung

`omni/free_look.py` veröffentlicht nach der bestehenden Body-Pipeline. Nach einem
Body-Setter wird dessen tatsächlicher Readback verwendet; im Idle der aktuelle
Sample. Ein aus zwei float32 bestehendes uint64 enthält Ziel-Yaw und Pitch-Faktor.
Der Animationsthread liest beides mit einem einzigen ausgerichteten 64-Bit-Load.
Es gibt keine neuen SDK-Getter, Timer, Ticks oder Eingabebelegungen.

`omni/native_free_look.py` erweitert den vorhandenen, exakt gebundenen Aim-Hook.
Mode 1 erhält den bisherigen Eingriff (Yaw null, Pitch unverändert). Mode 2
ersetzt im temporären Eingabevektor Yaw und multipliziert ursprünglichen Pitch.
Der dritte Wert, Argumente, GPRs, XMM0–2, MXCSR und Flags werden erhalten.
Beschädigte Werte führen im neuen Modus zu keinem Schreiben.

Normal- und Crouch-Knoten behalten Receiver-/Caller-Filter, Bind-Prüfungen,
Steam-Build-Fingerprint, vtable-/Code-Prüfungen sowie Owned-Restore. Kein neuer
Patch-Ort oder RVA. Beide Controls bleiben über den veröffentlichten Haupt-Control
gepinnt. Die ursprünglichen Native-Klassen und deren Audit sind unverändert.
Assemblerquelle und ausführbare Linux-Testfixture liegen im Native-Validation-Ordner.

Kamera, Body und Animation sind weiterhin Update-Snapshots. Die atomare Übergabe
verhindert gemischte Yaw/Faktor-Pakete, macht diese Spielbeobachtungen aber nicht
zu einer gemeinsamen atomaren Aufnahme. Die alten Report-Zähler
`aim_yaw_neutralizations` zählen jetzt auch die begrenzten Mode-2-Eingriffe.
Der ältere Phasenname `B_NEUTRAL_YAW` bezeichnet weiterhin die freie Basisphase.
Mit Pose-Diagnose enthält der aktuelle Sample zusätzlich `free_look`.

Die Dateien der Fahrzeugkorrektur .32 sind bytegleich. Weder die ADS-/Reticle-
Steuerung noch die bestehenden Bewegungseingaben wurden geändert.
