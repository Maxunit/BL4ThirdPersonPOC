# 0.3.9.21 Hybrid QA

Hybrid-Steuerung verschob die TPS-ADS-Kamera zusätzlich bis zu 35 cm nach vorne.
Das ließ besonders nahe Objekte größer wirken, obwohl beide Modi denselben
FOV-Zoompfad nutzen. Diese zusätzliche Annäherung wurde vollständig entfernt:
keine Dolly-Konstante, kein Dolly-Zustand, keine Fortschrittsberechnung, kein
Dolly-Befehl oder Statusfeld mehr. Auch der FPS→TPS-Rückweg endet wieder an den
regulären TPS-Kamera-Offsets. Die Scope-Überblendungen bleiben erhalten.

Hybrid wechselt weiterhin mit der konfigurierten Sprint-Aktion zwischen TPS-ADS
und nativem FPS-ADS. Globaler/Kategorie-Zoom und der native Waffenzoom folgen dem
normalen TPS-ADS-Pfad. .20s gezielte Waffenübergabe-Korrektur und .19s Omni-/
Fahrzeugoptimierungen sind unverändert enthalten. Hybrid ist optional, Standard aus.

Keine neuen Timer, Eingaben, Hooks oder nativen Patchstellen.
