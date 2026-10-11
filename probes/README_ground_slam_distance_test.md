# Erste Ground-Slam-Kameraprobe für 0.3.9.35

Dieser PyExec-Test verändert vorübergehend den Kameraabstand. .35 bleibt
installiert; gespeicherte Einstellungen werden nicht verändert.

## Ablauf

1. Vorige Diagnoseproben beenden. `ground_slam_distance_test.py` nach
   `sdk_mods` / in deinen bisherigen PyExec-Ordner kopieren.
2. Mit aktivem TPS `pyexec ground_slam_distance_test.py` ausführen und F1
   schließen. Auf normale TPS ohne Mausmenü warten.
3. Einen normalen Sprung ohne Slam ausführen: kein zusätzlicher Abstand.
4. Einen langen Slam ausführen: die Kamera erhält bis zu 80 cm mehr Abstand.
   Aufschlag, Kamerarückkehr und das akzeptierte Exit-„Oomph“ beurteilen.
5. Falls möglich auch einen kurzen Slam ausprobieren; drei bis fünf Sekunden
   nach der Rückkehr stillstehen.
6. Erneutes `pyexec ground_slam_distance_test.py` oder F10 stoppt, entfernt
   den Test und speichert die JSON. `RESTORED` nennt den vollständigen Pfad.
   Datei: `sdk_mods/settings/BL4ThirdPersonPOC_reports/ground_slam_distance_test_<UTC>.json`.

Bitte JSON und Eindruck zu Abstand, Ein-/Ausblenden und erhaltenem Exit-Effekt
zurückgeben. Kein Spielneustart zum Start/Stop erforderlich. Sicherheitsgrenze:
180 Sekunden einschließlich Startwartezeit oder 16.000 Updates.

## Verhalten und Umfang

Der verifizierte Getter `/Script/OakGame.OakCharacter:IsPerformingGroundSlam`
steuert den Abstand. Seine reine Bool-Signatur wird nochmals geprüft.
Der vorhandene Widget-Updatepfad interpoliert die zusätzliche Entfernung
mit dessen DeltaTime. Eintritt: exponentielle Reaktion, Zeitkonstante 0,08 s;
nach etwa 0,24 s sind rund 95 Prozent des Zielabstands erreicht. Bei einem Ende
in normalem TPS wird mit Zeitkonstante 0,06 s ausgeblendet. Bei GroundSlamExit
wird der eigene Zusatz entfernt; die bestehende .35-Exit-Kamerablende übernimmt.
Die tatsächliche Wirkung dieser Übergabe muss Ingame bewertet werden.

Ein temporärer Python-Wrapper ruft den unveränderten .35-Offset-Setter zuerst
auf. Auf dessen fertigen Offset wird die zusätzliche Entfernung entlang der
lokalen X-Achse angewendet. Root-Height-, Motion- und Shoulder-Anteile bleiben
in diesem Grundoffset. Mehrere Setter pro Update bauen den Anteil nicht auf:
der ursprüngliche Setter erzeugt jedes Mal wieder den aktuellen Grundwert.

FPS/ADS, Fahrzeuge, Shop, Leiter, Slide, Mausmenü, Lifecycle-/Mantle-Zustände
und fremde Kameramodi erhalten keinen Zusatz. Die Probe beendet sich bei
TPS-Deaktivierung, Fahrzeugeinstieg oder ungültigem/gewechseltem Owner.
Beim Stoppen wird der letzte selbst geschriebene Offset nur zurückgesetzt,
wenn sowohl seine Runtime-Identität als auch sein vollständiger Wert noch
übereinstimmen. Neuere Werte anderer Kamerapfade werden nicht überschrieben.
Anschließend wird der originale Python-Setter wiederhergestellt und der
einzige Widget-Beobachter entfernt. Der vorhandene Diagnoseplatz stellt
auch Cleanup durch F10, `bl4tps_height off` und Mod-Shutdown sicher.

Der Test schreibt ausschließlich den Kameraoffset. Keine FOV-, Profil-,
Actor- oder Animationsänderung und keine nativen Patches, Delegate-Bindungen,
zusätzlichen Producer oder Timer. Die JSON weist Kameraänderungen aus;
dies ist ausdrücklich keine rein lesende Diagnose und keine FPS-Benchmark.
PRE-Diagnosewerte können noch die Kamerawerte des vorigen Updates zeigen.

Prüfung: `python tests/ground_slam_distance_test_scenario.py`.
Zwölf lokale Tests mit simulierten SDK-Objekten und dem echten Loader/Router
prüfen normalen Sprung, Slam, ausbleibende Aufsummierung, erhaltene
Höhen-/Motion-/Profilwerte, unveränderte neuere Exit-Werte, den echten .35-
Setter mit Root-Korrektur, die Zustandsfilter, F10-/Shutdown-/Fehler-Cleanup,
Owner-Wechsel, Getter-Signatur und vergleichbare Interpolation bei 30/60/120 Hz.
Ingame-Kamerakollision und visuelle Exit-Wirkung sind damit nicht bewiesen.
