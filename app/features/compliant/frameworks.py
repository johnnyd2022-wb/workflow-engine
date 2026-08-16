"""Compatibility import for the NZ Alcohol module catalogue.

New code should import from ``modules.nz_alcohol.catalogue``.  Retaining this module avoids
breaking an early public seam while the Compliant platform gains further industry packs.
"""

from app.features.compliant.modules.nz_alcohol.catalogue import NZ_ALCOHOL_FRAMEWORKS, framework_by_slug

__all__ = ["NZ_ALCOHOL_FRAMEWORKS", "framework_by_slug"]
