"""NZ-alcohol domain constants — the single source of truth for the calculators.

No calculator module redefines these as literals; each imports from here (AC15).
"""

# Density of pure ethanol at 20 C, g/mL. Used for standard-drinks and ABV<->ABW.
ETHANOL_DENSITY_20C_G_PER_ML = 0.78924

# NZ (and Australia NZ Food Standards Code) standard drink = 10 g of pure ethanol.
NZ_STANDARD_DRINK_GRAMS_ETHANOL = 10.0
