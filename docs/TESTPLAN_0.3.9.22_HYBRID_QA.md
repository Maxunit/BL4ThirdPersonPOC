# 0.3.9.22 Hybrid QA – gezielter Test

1. Spiel vollständig beenden; alte Mod und Caches entfernen. Nur diese SDKMOD
   installieren. Keine PyExec-Proben parallel betreiben.
2. Beim Aktivieren muss `CLIENT_RESTART_HOOKS_VERIFIED pre=True post=True`
   erscheinen. `pre_return=False` ist bei bestätigter Registrierung zulässig.
3. Zu Fuß TPS und Omni einschalten, ADS loslassen. Einmal Fast Travel machen.
   Kameraverhalten bei Ankunft beschreiben und den SDK-Logabschnitt beilegen.
   Erwarteter Nachweis: `CLIENT_RESTART_SEEN` mit lokalen passenden Objekten
   sowie `CAMERA_LIFECYCLE_ARMED reason='client_restart'`.
4. Falls möglich: ins Hauptmenü, denselben Save laden. Kameraübergabe und Log
   vergleichen. Für diese QA ist kein bezahlter Respawn-Test erforderlich.
5. Einmal Fahrzeug rufen, aussteigen und landen; danach TPS-ADS und normalen
   Lauf prüfen. Die vorhandene Unterscheidung von Fahrzeug-Restarts bleibt.

Die erste Fragestellung ist die wieder vorhandene Registrierung und Übergabe.
Ein sichtbarer Restwechsel ist als eigener Befund zu melden. Diese Build
verspricht keine vollständig unsichtbare Ankunft und ändert keine Fallback-
Wartezeit oder native Kamera-Blend-Dauer.

Der alte `camera_restart_handoff_observer.py` ist auf .21 beschränkt und wird
hier nicht benötigt. Diagnose über die eingebauten Logmeldungen.
