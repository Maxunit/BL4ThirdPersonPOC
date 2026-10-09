# 0.3.9.18 – Granaten-Ausrichtung mit Zustandsnachlauf

Die bestätigte längere A/B-Variante ist in die Omni-Gameplay-Sitzung integriert.
Bei einem zugelassenen eigenen Offhand-Script bleibt die Ausrichtung bis zum
passenden lokalen ThrowGadget-Ereignis und anschließend während der bestehenden
Einhand-Aktionssperre zur Kamera gerichtet. Sperrenende, Scriptverlust, neuer
Gadget-/Feuer-/ADS-/Carry-Intent oder ungeeigneter Kontext beenden den Nachlauf.
Es gibt keine zusätzliche Wartezeit, keine Frame-Gnadenfrist und keine fest
zugeordneten physischen Tasten.

Ein sitzungseigener SDK-POST-Hook beobachtet ThrowGadget. Er prüft Signatur,
Game-Thread, aktiven Update-Owner, gebundenen Runtime-Kontext und lokalen Pawn.
Beim Session-Ende wird der Hook inaktiv und seine Entfernung überprüft;
fehlgeschlagenes Cleanup bleibt für einen erneuten Versuch registriert.
Optionale Zustandslesefehler beenden nur diese Korrektur. Es entsteht kein
zusätzlicher nativer Patch und es wird kein ThrowGadget-Aufruf ausgelöst.

Für erkannte Granaten ersetzt der native Handoff die bisherigen Montage-Frische-
und Quiet-Sample-Heuristiken. Andere, noch nicht vermessene Ordnance-Arten behalten
ihren bisherigen Fallback. Der Carry-Tracker für aufgehobene Objekte bleibt aktiv.
Der Report enthält grenade_facing_episodes, passende native Wurfereignisse,
Hook-Status und begrenzte optionale Lesefehler; Episoden werden nicht doppelt gezählt.

## Belege und Grenzen

Report omni_grenade_recovery_qa_20261009_190415_099219.json: 237 Samples,
drei passende native Würfe und drei Enden RECOVERY_UNLOCKED. Während des
Nachlaufs stimmt Körper-/Kamera-Yaw überein. Die Methode wurde wiederhergestellt,
alle Probe-Hooks entfernt; errors/read_errors/capture_limits sind leer.
QA bestätigt die längere Variante ausdrücklich als besser.

Die beobachteten etwa 0,59–0,60 s nach dem Wurf sind Messwerte, kein eingestelltes
Zeitintervall. Die Einhand-Sperre ist ein allgemeiner Zustand und kein bewiesenes
granadenspezifisches Animations-Endsignal. Die Bestätigung gilt für die getesteten
Granaten; andere Ordnance-/Hunter-Varianten bleiben gesondert zu prüfen.

313 lokale Tests: 309 bestanden, vier plattformbedingte Skips; davon 25 neue
Tests für Zustandsübergänge, Live-Daten-Replay, Integration und Hook-Cleanup.
Die integrierte .18 benötigt noch den kurzen Spieltest aus TESTPLAN_0.3.9.18.md.
