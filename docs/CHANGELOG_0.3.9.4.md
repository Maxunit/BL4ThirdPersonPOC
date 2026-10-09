# BL4ThirdPersonPOC 0.3.9.4 – Leere Waffe im Sprint hält Omni nicht mehr fest

Basis ist 0.3.9.3 (im Spiel bestätigt). **Im Spiel bestätigt am 09.10.2026** (Spieltest: funktioniert wie erwartet, ohne Logs).

## Fehlerbild (Omni an)
Mit leerer Waffe im Sprint nach hinten, links oder rechts feuern: Omni setzte aus, der Körper zeigte zur Kamera wie im normalen TPS-Verhalten. Das hielt an, bis der Sprint endete oder man stehen blieb. Nach vorn fiel es nicht auf.

## Ursache
Omni hat eine Sprint→Schuss-Brücke (`omni/combat_handoff.py`, SprintFireHandoff v2 aus dem Lab):
- BL4 beendet beim Feuern aus dem Sprint zuerst den Sprint. Der Schuss kommt erst nach `OakWeapon.PostSprintUseDelay` (gemessen 0,2 s).
- Damit der Körper in dieser Lücke nicht zuckt, hält die Brücke die Kampfausrichtung vom Druck bis zum nativen Schuss (`bIsFiring`).
- Die Brücke endet in folgenden Fällen:
  - mit dem Schuss;
  - bei Waffenwechsel oder Reload;
  - bei einem anderen Waffenzustand;
  - wenn BL4 wieder sprintet.

Ein abgelehnter Schuss (leeres Magazin, keine Reserve) liefert kein `bIsFiring`. Im Lab war das als offen notiert („abgelehnte Schüsse … noch offen“). Daraus entstand eine Selbstblockade:
1. Die Brücke hält die Kampfausrichtung. Dadurch pausiert Omni seine Sprint-Richtungs-Overrides.
2. Ohne diese Overrides erlaubt BL4 seitwärts oder rückwärts keinen Sprint.
3. Ohne Sprint endet die Brücke nie.

Nach vorn ist der Sprint nativ erlaubt. Dort endet die Brücke sofort, deshalb war vorn alles in Ordnung.

## Änderung
- Die Brücke gibt frei (`NATIVE_FIRE_NOT_ADMITTED`), wenn alle Bedingungen erfüllt sind:
  - die Feuertaste ist losgelassen;
  - es gab keinen Schuss;
  - BL4 sprintet nicht mehr;
  - seit dem Sprint-Ende ist mehr Zeit vergangen als das native `PostSprintUseDelay` der Waffe plus 0,25 s Toleranz.
  - Danach kann kein verzögerter Schuss mehr kommen.
- `PostSprintUseDelay` wird beim Scharfschalten aus der Waffe gelesen und muss zwischen 0 und 1,5 s liegen. Ist der Wert nicht lesbar, gilt der Messwert von 0,2 s.
- Gültige verzögerte Schüsse bleiben unverändert überbrückt. Ein gehaltener Abzug hält die Kampfausrichtung wie bisher, weil Feuern Kampf bedeutet.
- Ob BL4 danach selbst weitersprintet, entscheidet BL4. Nach einem Schuss aus dem Sprint muss man nativ ebenfalls neu sprinten.

## Diagnose
- Neu im Omni-Report:
  - `sprint_fire_episodes` (die letzten 32 Brücken):
    - Endgrund
    - Dauer
    - ob ein Schuss gesehen wurde
    - Sprint-Ende nach Druck
    - Sprint-Wunsch und Waffenzustand am Ende
    - gelesener Delay
  - `sprint_fire_not_admitted` (Zähler).
- Konsolenmeldung `SPRINT_FIRE_NOT_ADMITTED`. Sie erscheint nur mit `bl4tps_omni diag on`, sonst landet sie als Entwickler-Meldung im Log.

## Tests
- 120 Python-Tests, davon 10 neu.
- Geprüft:
  - Freigabe nach Delay
  - gehaltener Abzug
  - gültiger verzögerter Schuss
  - Waffen-Delay
  - Sprint-Wiederaufnahme
  - Begrenzung der Episoden
  - Lesen des Delays
  - Verdrahtung in `read_combat` mit Report und Meldung
- Native Templates und RVAs sind unverändert (Audit grün).
