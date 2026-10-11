# 0.3.9.29 – Bewegung, Ruckler-Logger, gestaffeltes Binden (Claude)

Basis: 0.3.9.28. Spielbefund zu .28: Stand 118–120 FPS (FrameGen), beim Laufen
bis 110, spürbarer Ruckler bei der ersten Bewegung nach dem Laden, kurzer
Ruckler beim Ein- und Aussteigen.

## Befund

**Laufen.** Omni kostete beim Laufen gut ein Drittel mehr als im Stand. Haupt-
posten: In Updates mit getauschten Dash-Clips (also bei fast jedem Geradeaus-
laufen) lief die komplette Kampf-Auswertung zweimal, samt Granaten-Scan mit
Pfadnamen pro Script. Dazu kommt: Im Stand passt Omnis Restkosten von etwa
1,5–2 ms noch in die Reserve unter dem 120er-Limit. Beim Laufen braucht das
Spiel selbst mehr CPU, die Reserve ist weg, und Omnis Restkosten werden sichtbar.
Wie groß der Anteil des Spiels ist, zeigt nur ein Vergleich Omni aus/an auf
derselben Strecke.

**Binden einer Session** (nach dem Laden, Respawn, Fahrzeug-Ausstieg). Lief
bisher in zwei langen Updates:
1. `install()`: komplette Knochenliste (eine SDK-Funktion pro Knochen),
   Reflexions-Scan der Movement-Klasse, voller Tastenbelegungs-Scan, obwohl das
   Lifecycle-Gate ihn gerade erst gemacht hatte.
2. Erstes RUN-Update: alle Native-Installationen (10 Patches), Reflexion über die
   Anim-Klasse, noch einmal die Knochenliste, Slide-Asset.

Fällt das Binden auf die erste Bewegung nach dem Laden, ist das genau der
beobachtete Ruckler. Beim Aussteigen passiert dasselbe Binden.

**Erste Bewegung.** Beim ersten Geradeauslaufen tauscht Omni die Dash-Clips und
ruft dafür `GetAnimationFromTag` auf. Ob das Spiel die Animation dabei
synchron von der Platte lädt, lässt sich offline nicht sagen. Der neue Logger
misst diesen Aufruf einzeln.

## Änderungen

1. **Ruckler-Logger** (`omni/hitch.py`, immer aktiv):
   - Jeder der drei Omni-Callbacks wird mit zwei Zeitstempeln gemessen.
   - Dauert einer 4 ms oder länger, erscheint in der Konsole eine Zeile `[OmniHitch]`
     mit den langsamsten benannten Schritten, höchstens 32 Zeilen pro Spielsitzung.
   - Benannte Schritte gibt es nur um einmalige Arbeit: `session.install`,
     `session.retire`, `bind.*`, `input.mapping_scan`, `clips.*.GetAnimationFromTag`,
     `vehicle.*`, `install.*`.
   - Die letzten 64 Ruckler stehen zusätzlich im `bl4tps_omni report` unter `hitches`.
   - Ruckelt es ohne eine solche Zeile, kam der Ruckler nicht aus Omnis Callbacks.
2. **Gestaffeltes Binden:**
   - Die sieben Bind-Schritte des ersten RUN-Updates (slide, vector, visual, sprint,
     route, root, entries) laufen jetzt einzeln, höchstens einer pro RUN-Update, in
     unveränderter Reihenfolge.
   - Die Pipeline startet, sobald alle Schritte erledigt sind. Omni übernimmt damit
     etwa 7 Updates (~0,1 s) später.
   - Pause- und Sonderzustände laufen wie bisher.
   - Die bisherigen Lazy-Stellen rufen dieselben `_bind_*`-Methoden auf.
   - Ein Fehler in einem Schritt stoppt mit `BIND_<SCHRITT>_FAILED`.
   - Gilt nur für Sessions, die über `install()` gebunden wurden.
3. **Knochen:**
   - In Produktion prüft `install()` die fünf geprüften Knochen per
     `GetBoneIndex`, das sind 5 SDK-Aufrufe statt einem pro Knochen.
   - Der Visual-Bind liest die Knochenliste nur noch mit Pose-Diagnose. Die Auswahl
     wurde ohnehin im Player-Bind wieder geleert.
4. **Movement-Schema:** Das Ergebnis des Reflexions-Scans wird pro Movement-Klasse
   (Weak-Identität und Adresse) im Rebind-Cache gehalten. Ein Rebind auf
   dieselbe Klasse scannt nicht erneut.
5. **Tastenbelegung beim Binden:** Die Session übernimmt den Leser des
   Lifecycle-Gates, wenn er denselben Controller hat und vollständig ist.
   Andernfalls läuft wie bisher ein voller Scan.
6. **Kampf-Auswertung einmal pro Callback:**
   - Der zweite Aufruf im selben Callback liefert den bereits ermittelten Zustand.
   - Nebeneffekt: Die Zustandsautomaten (Rising Edges, `NO_REQUEST_SAMPLES`) zählen
     jetzt auch beim Laufen einmal pro Update, wie im Stand und wie dokumentiert.
7. **Handler-Prüfung einmal pro Callback** (vorher zweimal beim Laufen).
8. **Granaten-Scan per Klassen-Identität:**
   - Die Offhand-Script-Klasse wird per `find_class` (oder an der ersten Instanz)
     als Weak-Identität gemerkt.
   - Danach gibt es keinen Pfadnamen-String mehr pro Script und Update.
   - Ist die Klasse nicht auffindbar, bleibt die Pfadprüfung.
9. **Fahrzeug-POST:** Der Air-Kontext übernimmt die im selben Callback aufgelöste
   Runtime. Die `live()`-Prüfung jedes Objekts bleibt.

## Zahlen (Zähl-Umgebung, pro Update, Lifecycle-PRE + Gameplay-POST)

| | .27 | .28 | .29 |
|---|---:|---:|---:|
| Stand: Property-Reads / UFunctions / Pfadnamen | 392 / 48 / 12,5 | 148 / 26 / 8,5 | 148 / 26 / 0,5 |
| Laufen: Property-Reads / UFunctions / Pfadnamen | 474 / 50 / 20,5 | 200 / 28 / 16,5 | 168 / 27 / 0,5 |
| Laufen mit Kameradrehung | 477 / 52 / 20,5 | 203 / 31 / 16,5 | 171 / 30 / 0,5 |
| Runtime-Auflösungen (alle Fälle) | 30–34 | 2 | 2 |

Der Laufen-Aufschlag gegenüber dem Stand sinkt von rund 0,5 ms (.28) auf rund
0,2 ms (Hochrechnung). Zum Binden gibt es keine Zählung: Die Native-
Installationen laufen unter Linux nicht.

## Geänderter Vertrag

- Omni übernimmt nach einem Binden etwa 7 RUN-Updates später.
- Kampf-Zustandsautomaten zählen pro Update, nicht pro Aufruf.
- Granaten-Tests: Der Test-Helfer teilt jetzt ein Klassen-Objekt für alle Scripts,
  wie es im Spiel ist.

## Unverändert

Native-Klassen und Templates (AST-Hash grün), Patch-Install und -Restore, Guards,
Hooks und Bewegungslogik.
