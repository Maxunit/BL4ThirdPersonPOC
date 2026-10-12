# 0.3.9.41 – lokale Validierung

Gesamtsuite: 599 Tests, 594 bestanden, fünf optionale übersprungen.
Ausgabe TEST_OUTPUT_0.3.9.41.txt. Zusätzlich Exit-Probe 17 und IdleInputs-Probe
24 SDK/native-memory-stubbed Szenarien; Facing-Probe sechs Szenarien.

Sieben neue Regressionstests prüfen 81 echte Special-/Publish-Durchläufe,
korrekte Exit-Gates und keinen transienten Standing-/Crouch-Aim-Eingriff; ein-
malige Validierung beim Erwerb; erneute Luftphase gibt Idle/Root frei; wiederholte
Publikation akzeptiert nur eigene Holds; Disarm vor normalem Publish und keine
spätere Schließung eines regulär neu geöffneten Guards; fehlender/geänderter
Idle-Guard publiziert keine Teilkontrollen; Combat und Shutdown schließen alle
Zuständigkeiten. Der bisherige echte Frame-Test Luft→Exit→eigene Rückkehr→Resume
läuft mit den neuen Exit-Erwartungswerten weiter. Alte .39/.40-Testwerte werden
für den laufenden aktuellen Code angepasst; Luft-Erwartungen bleiben gleich.

Native Replay: tests/slam_idle_native_replay_scenario.py und Fixture
slam_idle_update_1.10.2.json. Original-982-Byte-Update geprüft mit SHA256
6d23c416af99cb4bfda63f2f3f9e96a5f023ef2551412399dda8ecc141ca8dfd.
Unveränderter ScopedIdleUpdate-Prefix samt Hash in den kopierten Code eingebaut;
32 externe Call-/RIP-Daten-Ziele in lokale C/ms_abi-Helper/Daten relokiert.
Keine Game-DLL oder Spielsession verwendet. Getestet: eigene +/-177° bei Guard
0 wählt 2/1; bei Guard 1 wählt 0/0; fremde +/-177° bleibt 2/1; normal inaktiver
Node nutzt weiterhin Idle 0. Auswahl und generischer Update werden jeweils
aufgerufen, Dreh-Player-Seek nur auf aktivem Originalzweig. Guard-Counter zeigen
nur eigene Matches. Synthetische Eingaben, Konstanten, Vtables und Helper ersetzen
die Game-Umgebung. Keine Bestätigung gerenderter Animation oder Live-Privatwerte.

Diagnostischer privater Reader: nach SDK-reflektiert fehlenden Runtime-Scalars
nur dieselben fünf validierten Scope-Nodes und 24 Bytes bei 0x300; kein Pointer-
Follow. Layout nur beim exakten Originalcode-Hash, Worker-/Scope-/Anim-Identität,
Vtables und lesbarer committed Region. Unreviewtes Layout liest keine privaten
Offsets. Native Read-Kosten werden protokolliert. Erwartete Idle-Gates werden
gegenüber unerwarteten Aim-Gates unterschieden. Keine Produktionsänderung durch
Diagnose: sie ist ausschließlich standalone PyExec.

Produktions-Bytevergleich erwartet genau vier geänderte Dateien gegen .40:
Version in __init__.py/pyproject.toml und omni/session.py/omni/slam.py.
Alle 109 anderen Produktionsdateien, insbesondere native Templates/Fingerprints,
150-cm-Distanz, Root-Höhe und Widget-Zeitquelle, bleiben gleich. Paket: 113 Dateien,
CRC, eine Loader-Root, Quellgleichheit und drei Versionsfelder geprüft. Hashes:
PACKAGE_SHA256_0.3.9.41.json. Dev-ZIP aus getrackten Dateien ohne Caches/Git/dist,
CRC und alle Dateien gegen Quellen vor Ausgabe geprüft.

Offen: Nutzer-QA für ruhigen UND vollständig animierten Exit. Idle-Input-Wahl
ändert eine Graph-Auswahl trotz erhaltenem generischen Update; native Tests
können den sichtbaren kompletten Ground Slam hier nicht bestätigen.
