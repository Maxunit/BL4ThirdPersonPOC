# 0.3.9.10 – Native Sprint-Fire-Handoff QA

- Aim-Trace-Margin standardmäßig 70 cm statt 40 cm.
- Sprint-Fire-Handoff ohne zeitbasierte Freigabe: sowohl `PostSprintUseDelay`
  als auch der zusätzliche 0,25-s-Aufschlag wurden aus der Freigabeentscheidung
  entfernt. Der native Spiel-Timer selbst bleibt unverändert.
- Der Handoff beobachtet den nativen Sprint-Auftrag und die native Aktivität
  des primären Feuerverhaltens einschließlich des geprüften Charge-Getters.
- Ein losgelassener, noch ausstehender Auftrag bleibt geschützt. Bei leerem
  Magazin endet der Handoff nach beobachteter Auftragsschließung und Loslassen.
- Aufladen zählt als native Nutzung. Auch der Abbruch vor dem ersten Schuss
  wird anhand des Aktivitätsendes abgeschlossen; Report-Grund `NATIVE_USE_COMPLETED`.
- Unbekannte Feuer-/Zusatz-Getter erhalten keinen geratenen Zustandsleser und
  keine Timer-Ersatzlogik. Der native Handoff ist für diese Verhalten nicht aktiv;
  normale reflektierte Kampfzustände bleiben wirksam. Status im Omni-Report:
  `sprint_fire_native.supported=false` mit Grund.
- Build-/Code-Prüfung vor nativen Zustandslesungen, erneut geprüfte dynamische
  Bindungen, keine neuen SDK-Hooks, nativen Aufrufe oder Code-Patches für diesen Fix.
- Vorhandene Throwable-Zoom- und Omni-Status-Korrekturen der Repo sind enthalten.

## Prüfung

163 Python-Tests bestanden, drei optionale/umgebungsabhängige Tests übersprungen.
Aufgezeichnete Spieltests mit normaler Schusswaffe und Charge-Assault-Rifle
werden mit zwei stark unterschiedlichen Zeitmaßstäben reproduziert: gleiche
Handoff-Phasen. Native Getter-Verzweigungen und ungültige Bindungen separat geprüft.
Vorhandene native Idle-Scope- und Movement-Prüfungen bestanden.
Die integrierte Build benötigt noch den Gameplay-Nachtest.
