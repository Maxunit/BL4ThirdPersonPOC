# Spieltest 0.3.9.18

Die längere Granaten-A/B-Variante ist bestätigt; dieser Test prüft ihre Integration.
Die vorherige Recovery-Probe wurde laut Report vollständig beendet und restauriert.
Spiel regulär schließen, die bisherige SDKMOD durch dist/BL4ThirdPersonPOC.sdkmod
ersetzen und mit TPS und Omni starten. Keine zusätzliche pyexec-Probe nötig.

1. Drei Granaten beim seitlichen bzw. rückwärtigen Laufen werfen. Die Ausrichtung
   soll während des Wurfs und Nachlaufs wie in der bestätigten Recovery-Probe wirken.
2. Ein aufgehobenes Objekt werfen. Die bestätigte Ausrichtung aus .17 soll erhalten bleiben.
3. Während eines Granaten-Nachlaufs Feuer bzw. ADS drücken. Der zusätzliche
   Granaten-Hold muss enden; normale Combat-Ausrichtung darf weiterhin greifen.
4. Omni aus- und wieder einschalten, anschließend nochmals eine Granate werfen.
   Kein festhängender Nachlauf und keine doppelt registrierten Hooks.
5. TPS aus/ein und bei Gelegenheit Save-/Map-Wechsel prüfen. Die alte Sitzung
   muss ihren Hook entfernen; die neue Sitzung muss ihren eigenen Hook binden.
6. Normalbewegung, Hybrid-ADS und Sprint-Feuer kurz gegenprüfen und Report speichern.

Im Report sollen zugelassene grenade_facing_episodes passende native_throw_t
und beim ununterbrochenen Nachlauf RECOVERY_UNLOCKED zeigen. Fehlerlisten prüfen.
Nach dem Session-Ende muss grenade_facing_sdk_hook false sein. Während der
laufenden Omni-Sitzung ist ein zusätzlicher SDK-Hook vorgesehen; die Korrektur
fügt keinen nativen Patch hinzu.

Andere Ordnance-Arten, Hunter, Controller und längere Gameplay-Sitzungen bleiben
gesonderte Tests. Die gemeinsam genutzte Einhand-Sperre wird nur zusammen mit
dem eigenen zugelassenen Script und beobachteten Wurf verwendet; daraus folgt
keine universelle Aussage über das Ende jeder Granatenanimation.
