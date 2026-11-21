"""Build gzip sidecars for the public JS and CSS served by WhiteNoise."""

import gzip
from pathlib import Path

from app.core.backend.static_assets import CORE_SLICE_FRONTENDS, iter_core_assets, register_core_feature_assets

APP = Path(__file__).resolve().parents[1] / "app"


def compress(asset: Path) -> None:
    body = asset.read_bytes()
    compressed = gzip.compress(body, mtime=0)
    if len(compressed) < len(body) * 0.95:
        asset.with_name(asset.name + ".gz").write_bytes(compressed)


def main() -> None:
    for feature in CORE_SLICE_FRONTENDS:
        register_core_feature_assets(feature, APP / "features" / feature / "frontend")
    for _, name, directory in iter_core_assets():
        compress(directory / name)

    crm = APP / "features/crm/frontend"
    for kind in ("js", "css"):
        for asset in (crm / kind).glob(f"*.{kind}"):
            if asset.is_file() and not asset.is_symlink():
                compress(asset)


if __name__ == "__main__":
    main()
