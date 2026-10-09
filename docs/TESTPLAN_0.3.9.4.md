# Testplan 0.3.9.4 – Leere Waffe im Sprint

Installation wie bisher: die `.sdkmod` ersetzen und `__pycache__` löschen. Omni an, vorher `bl4tps_omni diag on` eingeben.

## 1. Fehlerbild nachstellen
1. Eine Waffe leer schießen, möglichst ohne Reserve. Bei vorhandener Reserve lädt BL4 nach, das ist ein eigener Fall (Punkt 3).
2. Im Sprint nach links, rechts und hinten jeweils einmal kurz feuern (antippen).
3. Erwartet:
   - Während und kurz nach dem Druck zeigt der Körper zur Kamera wie bisher.
   - Spätestens etwa eine halbe Sekunde nach dem Loslassen folgt der Körper wieder der Bewegung (Omni).
   - In der Konsole steht `SPRINT_FIRE_NOT_ADMITTED`.
4. Bitte notieren: Sprintet die Figur danach von selbst weiter, oder muss Sprint neu gedrückt werden?
5. Dasselbe mit gehaltenem Abzug, etwa 1 s halten, dann loslassen. Erwartet: Beim Loslassen kehrt Omni sofort zurück.

## 2. Regression: geladene Waffe
1. Im Sprint nach vorn, links, rechts und hinten kurz feuern und mit gehaltenem Abzug feuern.
2. Erwartet wie bisher: Der Schuss kommt, es gibt kein Zucken beim Übergang Sprint→Schuss, und danach übernimmt wieder Omni.
3. In der Konsole darf hier **kein** `SPRINT_FIRE_NOT_ADMITTED` stehen.

## 3. Leeres Magazin mit Reserve
1. Magazin leer, aber Reserve vorhanden. Im Sprint seitlich feuern, BL4 startet den Reload.
2. Erwartet: Omni hängt nicht. Der Körper folgt nach dem Reload-Start wieder der Bewegung.

## Was zurückschicken
- Die Antwort zu Punkt 1.4.
- Nach den Punkten 1–3 `bl4tps_omni report` eingeben und die JSON aus `sdk_mods/settings/BL4ThirdPersonPOC_reports/` schicken. Wichtig darin sind `sprint_fire_episodes` und `combat_transitions`.
- Falls Omni weiterhin hängt: kurz notieren, bei welcher Variante.
