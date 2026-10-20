"""Costing fields are private inventory data; existing CP stays until costing is entered."""
import math

FIELDS = ('beadKg', 'beadCostKg', 'laborHours', 'otherMaterialCost')

def normalize(product, previous=None):
    previous = previous or {}
    for key, limit in (('beadsUsed', 2000), ('notes', 4000)):
        value = product.get(key, previous.get(key, ''))
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('Invalid inventory ' + key)
        product[key] = value
    changed = False
    for key in FIELDS:
        value = product.get(key, previous.get(key, 0))
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e9:
            raise ValueError('Invalid non-negative inventory ' + key)
        changed = changed or value != previous.get(key, 0)
        product[key] = value
    enabled = product.get('costingEnabled', previous.get('costingEnabled', False))
    if type(enabled) is not bool:
        raise ValueError('Invalid costing flag.')
    product['costingEnabled'] = enabled or previous.get('costingEnabled', False) or changed
    if product['costingEnabled']:
        cost = product['beadKg'] * product['beadCostKg'] + 50 * product['laborHours'] + product['otherMaterialCost']
        if not math.isfinite(cost) or cost > 1e9:
            raise ValueError('Calculated CP exceeds the inventory limit.')
        product['cp'] = math.floor(cost * 100 + .5) / 100
    return product
