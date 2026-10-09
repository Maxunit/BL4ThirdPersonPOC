import unittest
from support import S, prop
from BL4ThirdPersonPOC.omni.weapon_fire_diagnostics import WeaponFireDiagnostics


class DiagnosticTests(unittest.TestCase):
    def test_reflected_candidates_and_changed_values_only(self):
        properties = [prop('AmmoCount', 'IntProperty', 8),
                      prop('bPendingFire', 'BoolProperty', 16),
                      prop('Unrelated', 'IntProperty', 20)]
        weapon = S(Class=S(_properties=lambda: properties, _superfields=lambda: ()),
                   _path_name=lambda: 'Weapon_Test', AmmoCount=0, bPendingFire=False)
        report = {}; d = WeaponFireDiagnostics(report)
        for i in range(3):
            d.sample(weapon, update=i, phase='WAIT_NATIVE_FIRE', fire=False, firing=False)
        diag = report['weapon_fire_diagnostic']
        self.assertEqual(len(diag['observations']), 1)
        self.assertEqual(diag['observations'][0]['values'], {'AmmoCount': 0, 'bPendingFire': False})
        weapon.bPendingFire = True
        d.sample(weapon, update=4, phase='WAIT_NATIVE_FIRE', fire=False, firing=False)
        self.assertEqual(len(diag['observations']), 2)
        self.assertEqual(diag['errors'], [])

    def test_missing_optional_property_records_error_without_gameplay_failure(self):
        weapon = S(Class=S(_properties=lambda: [prop('AmmoCount', 'IntProperty', 8)],
                           _superfields=lambda: ()), _path_name=lambda: 'Weapon_Test')
        report = {}; d = WeaponFireDiagnostics(report)
        d.sample(weapon, update=0, phase=None, fire=False, firing=False)
        self.assertEqual(len(report['weapon_fire_diagnostic']['errors']), 1)
