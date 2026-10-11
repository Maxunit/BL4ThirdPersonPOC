# 0.3.9.24 – Reticle Equip QA

## Korrigierter Pfad

.23 beendet die ADS-Darstellung bei einer nativen Zoom-Unterbrechung und beginnt
sie erneut nach der nativen Wiederaufnahme. Dabei werden Handoff-Zähler neu
gebunden. Die alte Equip-POST-Funktion veröffentlichte das Reticle ausschließlich
beim zweiten beobachteten Callback; spätere Callbacks wurden ganz ignoriert.

Ein Reticle, das beim ADS-Einstieg als bereits sichtbar gemeldet wird, beendet
außerdem die Pending-Publikation. Verändert der native Equip-Body dieses Modell
anschließend, reicht diese frühere Sichtbarkeitsmeldung nicht aus.

Diese Reihenfolgen fehlten in den .23-Tests. Mit simuliertem Modell scheitern
vier gezielte Fälle gegen den unveränderten .23-Code. Das ist ein Nachweis der
Code-Lücke, keine Messung des konkreten .23-Live-Laufs.

## Änderung

- Jede tatsächliche lokale `OnWeaponEquipped`-POST-Meldung prüft die aktuelle
  TPS-ADS-Identität und fordert die bestehende guarded Reticle-Publikation an.
  Ein vormals als sichtbar gemeldetes Modell kann dadurch erneut geprüft werden.
- Die Veröffentlichung braucht weder einen zweiten verbleibenden Callback noch
  einen neuen physischen ADS-Press. Gezählte Callback-Paare bleiben für die
  bestehenden nativen Rearm-/Modifier-Gates erhalten und werden nicht erfunden.
- Erfolgt der ADS-Einstieg im nativen Equip-Body nach PRE, kann POST die nun
  aktive lokale Waffen-/Collector-Identität übernehmen.
- Ein aktives lokales Weapon mit erfolgreicher guarded Publikation beendet die
  Reticle-Rebind-Sperre auch nach einem einzigen verbliebenen Callback. Damit
  bleibt der Hybrid-Scope nicht allein wegen der alten Paarbedingung gesperrt.
- Vorübergehend fehlende native Readiness bleibt Pending; der bestehende
  Änderungsabgleich übernimmt. Fremde Waffen/Collector, andere Kamera-Besitzer,
  FPS-Routen und Native State 0/3 dürfen keinen TPS-Reticle-Einstieg erzeugen.
- Die Publikationsanforderung liegt als testbare Funktion in `ads_handoff.py`;
  der Loader delegiert. F10 zeigt den letzten Reticle-Event und Status.

## Umfang

Paketänderungen gegenüber .23 ausschließlich in `ads_handoff.py`,
`ads_qa_snapshot.py`, Loader und Versionsmetadaten. Der native Reticle-Publisher,
ADSController, FOV-Steuerung, native Lifecycle-/Patch-Module und nativen
Modifier-Gates sind unverändert. Keine zusätzlichen Hooks, Scans oder Timer.

Der bisherige `.23`-Spielbefund bleibt eine Regression. `.24` ist die gezielte
QA-Korrektur und wird erst durch denselben Spieltest bewertet.
