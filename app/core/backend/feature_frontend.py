"""Mount a Core slice's templates and public assets under the existing Core URLs."""

from pathlib import Path

from flask import Blueprint
from jinja2 import ChoiceLoader, FileSystemLoader

from app.core.backend.static_assets import register_core_feature_assets

_FEATURES = Path(__file__).resolve().parents[2] / "features"


def register_core_feature_frontend(bp: Blueprint, *features: str) -> None:
    template_loaders = [bp.jinja_loader]
    for feature in features:
        frontend = _FEATURES / feature / "frontend"
        register_core_feature_assets(feature, frontend)
        template_loaders.append(FileSystemLoader(frontend / "templates"))
    bp.jinja_loader = ChoiceLoader(template_loaders)
