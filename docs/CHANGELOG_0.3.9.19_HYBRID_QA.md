# 0.3.9.19 Hybrid QA – Bug-Inventur

Diese separate Variante basiert exakt auf der regulären 0.3.9.19 QA.
Einzige Änderung im Mod-Paket: `HYBRID_ADS_AVAILABLE = True` statt False.
Der vorhandene Menü-/Konsolen-Setter sowie die Laufzeit können die Option dadurch
wieder aktivieren. Standard der Option bleibt aus; gespeicherte Einstellungen
werden regulär geladen. Hybrid benötigt weiterhin eine aktive Omni-Gameplay-Sitzung.

Keine Änderung an Zoom-Berechnung, Scope-Routen, Sniper-Einstellung, nativen
Templates, Omni-Caches, Fahrzeug-Handoffs oder Cleanup. Keine zusätzliche Messprobe.
Die reguläre 0.3.9.19 QA mit gesperrtem Hybrid bleibt separat verfügbar.

## Gemeldete Abweichungen, noch zu untersuchen

- Unterschiedliche native ADS-Vergrößerungen der Waffen/Waffenkategorien scheinen
  im Hybrid-Modus nicht berücksichtigt zu werden.
- Globaler und pro Waffenkategorie manuell eingestellter Mod-ADS-Zoom scheinen
  im Hybrid-Modus nicht berücksichtigt zu werden.
- Der Wechsel TPS-ADS↔FPS-ADS über die aktuelle Sprint-Belegung hat weitere Fehler.
- Die konfigurierte ADS-Route für Sniper Rifles scheint im Hybrid-Modus nicht
  berücksichtigt zu werden.

Diese Punkte sind Gameplay-Beobachtungen, keine bestätigten Ursachen. Der Hybrid-Code
enthält aktuell einen eigenen Zoom-Deckel und eine TPS-Halteroute für alle Kategorien.
Ob deren Verhalten den einzelnen Symptomen vollständig zugrunde liegt, muss anhand
konkreter Reproduktionen getrennt geprüft werden.
