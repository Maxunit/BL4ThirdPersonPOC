# Reparaturstand nach 0.3.9.13

Stand: 09.10.2026. Claudes Audit dient als Prüfliste; seine weiteren Befunde
sind hier nicht pauschal als unabhängig bestätigte Fehler eingestuft.

| Aufgabe | Nachweis / Status | Nächster Schritt |
|---|---|---|
| Hybrid-ADS beendet Omni bei ADS + Sprint | .14-Spieltest: acht Scope-Tastendrücke, 198 Scope-Pausen-Updates, RUNNING und keine Fehler; QA bestätigt funktionierende Wechsel | Für diesen Ablauf live bestätigt; weitere Eingabefolgen weiter prüfen |
| Zoom-Reset bei FPS-ADS → gehaltenem TPS-ADS | .15-Spieltest: QA bemerkt keinen Aussetzer mehr; sechs vollständige Rückwege mit FOV von ca. 16,26° direkt auf 66,67°, ohne Zwischenkehr zur 90°-Hüft-FOV und ohne neuen ADS-Übergang; RUNNING, keine Fehler | Für den getesteten gehaltenen Sniper-Rückweg live bestätigt; Abbruch und Waffenwechsel weiterhin gesondert beurteilen |
| Throwable-Körperrotation | .17-Spieltest 175826: QA bestätigt natürliche Wurfdrehung. Eine Episode, Objektfreigabe beobachtet, Ende CARRY_CONTEXT_ENDED; Körper-/Kamera-Yaw von etwa 180° auf 0°, danach Rückkehr zur Bewegungsausrichtung. RUNNING, keine Root-/Gameplay-Fehler. | Für den getesteten Wurf eines aufgehobenen Objekts live bestätigt. Andere Throwable-Arten sowie Controller und allgemeine Eingaberegression weiter gesondert prüfen. |
| Granaten-Körperrotation endet vor Wurfanimation | .17-Report 180246: zehn Gadget-Episoden mit montage=null, Ende NO_MONTAGE nach 0,0974–0,1396 s. Observer 181618: zwei Würfe; Omni-Hold endet nach 0,122/0,088 s, OneHandWeaponActionLock nach 0,948/0,919 s, Script_LTrick_HandleOffhand nach 1,273/1,233 s. Kein Gameplay-Fehler, keine Capture-Limits; zehn optionale Reads auf nicht unterstützte Delegate-/Map-Typen. Das genaue Wurf-Endsignal ist noch nicht belegt. | Lesende omni_grenade_end_observer.py: konkrete Offhand-Script-Felder und lokaler ThrowGadget-POST vergleichen; JSON verlustfrei als Felddifferenzen speichern. SDK-POST kann direkte native Aufrufe verpassen. Keine allgemeine Lock-/Script-Dauer pauschal als Wurfanimation übernehmen; keine Zeitverlängerung. |
| Montage-/Sprint-Fire-Gnadenfristen aus .12 | Pauschale zwei Samples bzw. Montage-Frische ≤ 0,15 s im Code | Zustandsbelege prüfen; Frame-Zählung allein bestätigt keinen nativen Zustand |
| Weitere Hybrid-Punkte H1–H5 | H2 im ersten Reparaturschritt berücksichtigt; andere Audit-Aussagen noch einzeln zu prüfen | Gezielte Nachprüfung nach Übergabe-QA |
| Objektlebenszeiten S1/S6 und Shop-Reset S2 | Audit-Prüfkandidaten | Setzen, Lesen, Owner-Wechsel und Cleanup unabhängig prüfen |
| Omni O1–O3, Schulter S5, Kamera L1 | Audit-Prüfkandidaten | Reproduktion und kleine getrennte Fixes |
| Item-Card-Wachstum N1, Patch-Lebenszyklus N2 | Audit-Prüfkandidaten mit nativer Tragweite | Ablauf und tatsächliche Speicher-/Thread-Eigenschaften nachweisen |
| Beam-Tiefe aus .12 | Neue native Änderung; Wirkung und Deckungskonflikt noch nicht gemeinsam live beurteilt | Eigener Test und gezielte technische Prüfung |
| Großer Omni-Umbau / Aufräumen | Zurückgestellt | Erst stabile referenzierte Gameplay-Abläufe; getestete A/B-Korrekturen einzeln bewerten |

Leitlinien: Zustandswechsel durch belegte Ereignisse/Zustände; visuelle
Interpolation getrennt behandeln. Optionaler Diagnosefehler darf nicht
automatisch Gameplay stoppen. Fehlgeschlagene native Owner-/Restore-Prüfung
bleibt sicherheitsrelevant und wird nicht pauschal ignoriert. Grüne SDK-Stubs
ersetzen keine Live-Prüfung.

## Granaten-Wurfereignis – Observer 184624

244 Samples, 19 Ereignisse, zwei lokale ThrowGadget-POST-Aufrufe;
MANUAL_STOP, errors/read_errors/capture_limits leer, beide Probe-Hooks entfernt.
Offhand-Script exponiert nur MyActor, keinen eindeutigen Animations-Endzustand.
ThrowGadget tritt nach etwa 0,359 und 0,328 s auf; Omni hatte bereits nach
etwa 0,101 und 0,126 s freigegeben. Lock und Script bestehen danach weiter.

Temporäre omni_grenade_handoff_qa.py für .17: neuer eigener Offhand-Script
zusammen mit konfiguriertem Gadget-Intent hält die vorhandene Omni-Ausrichtung
bis zum passenden lokalen ThrowGadget-POST. Scriptverlust/ungeeigneter Kontext
beenden die Korrektur. Keine Zeiten oder Frame-Gnadenfrist; vorhandener
Carry-Tracker bleibt wirksam. 17 lokale QA-Tests inklusive Live-Daten-Replay,
SDKMOD-/zipimport-Quellprüfung und Cleanup bestanden. Visuelles Nachschwingen
nach dem nativen Wurf muss live beurteilt werden; noch kein Produktionsfix.

## Granaten-Handoff-QA – Report 185623

QA bestätigt technisch korrekte Würfe, wünscht jedoch einen etwas längeren
visuellen Nachlauf ohne Timer. Drei admitted Episoden, drei passende lokale
ThrowGadget-Aufrufe nach 0,353/0,366/0,369 s. Bei allen drei Würfen beträgt
Körper-/Kamera-Yaw-Abweichung bei Freigabe 0°. method_restored=true, alle Hooks
entfernt, errors/read_errors/capture_limits leer.

Die Einhand-Aktionssperre endet 0,617/0,631/0,620 s nach dem Wurf; der eigene
Offhand-Trick verschwindet erst nach weiteren etwa 0,91–0,94 s. Ein Timer ist
daraus nicht abgeleitet. Separate omni_grenade_recovery_qa.py hält nach dem
beobachteten Wurf nur bei bestehender Sperre und demselben zugelassenen eigenen
Script. Sperrenende, Scriptverlust, neuer Action-Intent oder ungeeigneter
Kontext beenden den Nachlauf. Die Sperre ist allgemein; sie ist kein bewiesenes
grenadenspezifisches Animations-Endsignal. 24 lokale Tests einschließlich Replay
der drei Würfe bestanden; längere visuelle Variante zum damaligen Stand noch nicht live bestätigt.

## Granaten-Recovery bestätigt – Report 190415 und Integration .18

QA bestätigt die längere Ausrichtung ausdrücklich als besser. 237 Samples,
drei passende ThrowGadget-Ereignisse, drei RECOVERY_UNLOCKED-Episoden mit
Gesamtdauer 0,937/0,934/0,945 s und Nachlauf 0,598/0,592/0,603 s. Körper-/Kamera-Yaw
bleibt im Nachlauf deckungsgleich. method_restored=true, Probe-Hooks entfernt,
errors/read_errors/capture_limits leer. Diese Zeiten sind beobachtet, nicht konfiguriert.

.18 integriert die bestätigte Zustandslogik als sitzungseigenen Controller ohne
Methoden-Override. Ein lokaler SDK-POST-Hook wird mit Owner-/Thread-/Runtime-Prüfung
und überprüfbarem Cleanup gebunden. Erkannte native Granaten supersedieren den
alten Montage-/Quiet-Sample-Pfad; andere Ordnance behält den bisherigen Fallback.
Carry bleibt aktiv. 25 neue Regressionstests; insgesamt 313 Tests, 309 bestanden,
vier plattformbedingte Skips. Der kurze Integrationstest der .18 im Spiel steht
noch aus. Die allgemeinen Audit-Punkte gelten dadurch nicht als erledigt.
