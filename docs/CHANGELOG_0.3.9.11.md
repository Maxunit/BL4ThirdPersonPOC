# 0.3.9.11 – Freefall rotation polishing

Die freie Körperdrehung beim Richtungswechsel in der Luft folgt dem Zielwinkel
mit maximal 540 Grad pro Sekunde, wie die Bewegungsdrehung am Boden. Bisher
wurde der vollständige Winkel in einem Update übernommen.

Die Kampf-Drehung bleibt unverändert. Native Dashes, angeforderte Dash-Zyklen
und besondere Bewegungsmodi behalten ihre bisherige Ausrichtung. Eine lediglich
vorbereitete Dash-Eingabe blockiert die Glättung noch nicht.

Direkte Integration der akzeptierten A/B-Probe v2; keine dynamische Quellcode-
Prüfung oder Instanzüberschreibung mehr nötig. Keine neuen Hooks oder Patches.
Die Änderungen aus 0.3.9.10 bleiben enthalten: 70 cm Aim-Trace-Margin und native
Sprint-Fire-Zustandsprüfung einschließlich geprüftem Charge-Verhalten.

Spieltest der Probe: 285 Luft-Updates, 206 begrenzte Drehschritte, keine Fehler,
alle geprüften Schritte innerhalb der Drehgeschwindigkeit; Original wiederhergestellt.
Der aufgezeichnete Lauf enthält nur freie Fallzustände. Kampf-/Dash-Ausnahmen
wurden lokal geprüft; ein kurzer Nachtest der integrierten Build bleibt sinnvoll.

Nachtest: W/S und A/D im freien Fall, Loslassen, Landen, Air-Dash und Feuern
in der Luft. Die bisherigen A/B-Proben nicht starten.
