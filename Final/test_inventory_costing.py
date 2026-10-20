import unittest
import inventory_costing as costing

class InventoryCostingTests(unittest.TestCase):
    def test_formula_fractional_kg_and_hours(self):
        p = {'cp':0, 'beadKg':.25, 'beadCostKg':800, 'laborHours':1.5, 'otherMaterialCost':25}
        costing.normalize(p)
        self.assertEqual(p['cp'], 300)
        self.assertTrue(p['costingEnabled'])

    def test_legacy_cost_stays_until_inputs_are_entered(self):
        p = costing.normalize({'cp':420})
        self.assertEqual(p['cp'],420)
        self.assertFalse(p['costingEnabled'])
        updated = costing.normalize({**p,'laborHours':2},p)
        self.assertEqual(updated['cp'],100)
        # Resetting all costing inputs to zero must produce zero CP.
        zero = costing.normalize({**updated,'laborHours':0},updated)
        self.assertEqual(zero['cp'],0)
        self.assertTrue(zero['costingEnabled'])

    def test_stale_clients_preserve_costing_fields(self):
        prior = costing.normalize({'cp':0,'beadKg':.1,'beadCostKg':500,'notes':'Keep me'})
        p = costing.normalize({'cp':999},prior)
        self.assertEqual(p['cp'],50)
        self.assertEqual(p['notes'],'Keep me')

    def test_negative_nonfinite_and_oversized_values_are_rejected(self):
        for value in (-1, float('nan'), float('inf'), '1', True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                costing.normalize({'cp':0,'beadKg':value})
        with self.assertRaises(ValueError):
            costing.normalize({'cp':0,'beadKg':1e9,'beadCostKg':1e9})

if __name__ == '__main__':
    unittest.main()
