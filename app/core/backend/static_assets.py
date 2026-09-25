"""Registry for public Core JS/CSS assets owned by backend feature slices.

Feature frontends may opt in by registering their flat ``frontend/js`` and
``frontend/css`` directories during route registration. Only those explicitly
registered directories are scanned; other feature assets keep their own auth and
serving rules.
"""

from __future__ import annotations

from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[2]
_FEATURES_DIR = (_APP_DIR / "features").resolve()
_CORE_FRONTEND_DIR = (_APP_DIR / "core" / "frontend").resolve()
_KINDS = {"js": ".js", "css": ".css"}
_CORE_ASSET_FEATURES = frozenset(
    {
        "activity_log",
        "dashboard",
        "demo_data",
        "reconciliation",
        "wastage",
        "compliance_checks",
        "traceability",
        "inventory",
        "process_design",
        "execution",
        "shell",
    }
)

_ASSET_DIRS: dict[str, list[Path]] = {kind: [(_CORE_FRONTEND_DIR / kind).resolve()] for kind in _KINDS}


def _build_registry() -> dict[str, dict[str, Path]]:
    registry: dict[str, dict[str, Path]] = {kind: {} for kind in _KINDS}
    for kind, extension in _KINDS.items():
        for directory in _ASSET_DIRS[kind]:
            if not directory.is_dir():
                continue
            for asset in directory.iterdir():
                if asset.is_symlink() or not asset.is_file() or asset.suffix.lower() != extension:
                    raise ValueError(f"Core {kind} asset directory contains a non-public entry: {asset}")
                previous = registry[kind].get(asset.name)
                if previous is not None and previous != directory:
                    raise ValueError(f"Duplicate Core {kind} asset name {asset.name!r} in {previous} and {directory}")
                registry[kind][asset.name] = directory
    return registry


_ASSET_REGISTRY = _build_registry()


def register_core_feature_assets(feature: str, frontend_dir: str | Path) -> None:
    """Register a feature slice's public flat JS/CSS folders for Core URLs.

    The caller must pass ``app/features/<feature>/frontend``. Registration is
    deliberately explicit so authenticated CRM/Compliance assets are not exposed by
    Core's public static routes or WhiteNoise.
    """
    if feature not in _CORE_ASSET_FEATURES:
        raise ValueError(f"Invalid feature slice name: {feature!r}")
    frontend = Path(frontend_dir)
    expected = _FEATURES_DIR / feature / "frontend"
    if frontend.is_symlink() or frontend.resolve() != expected.resolve() or not frontend.is_dir():
        raise ValueError(f"Core assets must come from the registered slice frontend: {expected}")

    additions: dict[str, Path] = {}
    for kind in _KINDS:
        candidate = frontend / kind
        if candidate.exists() or candidate.is_symlink():
            if not candidate.is_dir() or candidate.is_symlink():
                raise ValueError(f"Invalid Core {kind} asset directory: {candidate}")
            directory = candidate.resolve()
            if not directory.is_relative_to(expected.resolve()):
                raise ValueError(f"Invalid Core {kind} asset directory: {directory}")
            additions[kind] = directory

    for kind, directory in additions.items():
        if directory not in _ASSET_DIRS[kind]:
            _ASSET_DIRS[kind].append(directory)
    global _ASSET_REGISTRY
    _ASSET_REGISTRY = _build_registry()


def core_asset_directory(kind: str, filename: str) -> Path | None:
    """Resolve a whitelisted asset basename to its registered owner directory."""
    if kind not in _KINDS or not filename or Path(filename).name != filename:
        return None
    if Path(filename).suffix.lower() != _KINDS[kind]:
        return None
    return _ASSET_REGISTRY[kind].get(filename)


def core_asset_directories(kind: str) -> tuple[Path, ...]:
    """Return registered public roots in the same order used by the filename map."""
    if kind not in _KINDS:
        return ()
    return tuple(_ASSET_DIRS[kind])


def iter_core_assets() -> tuple[tuple[str, str, Path], ...]:
    """Yield (kind, filename, directory) rows for cache-version digests."""
    return tuple(
        (kind, filename, directory) for kind in _KINDS for filename, directory in sorted(_ASSET_REGISTRY[kind].items())
    )
