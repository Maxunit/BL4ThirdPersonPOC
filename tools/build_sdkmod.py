"""Package BL4ThirdPersonPOC/ as dist/BL4ThirdPersonPOC.sdkmod.

The Oak2 loader accepts a .sdkmod only when the zip holds exactly one root
folder named like the file (without suffix). Caches are excluded.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'BL4ThirdPersonPOC'
DIST = ROOT / 'dist'


def build():
    DIST.mkdir(exist_ok=True)
    target = DIST / (PACKAGE.name + '.sdkmod')
    files = sorted(p for p in PACKAGE.rglob('*')
                   if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(PACKAGE.parent).as_posix())
    # Same structural rule the loader applies.
    entries = list(zipfile.Path(target).iterdir())
    if len(entries) != 1 or entries[0].name != target.stem:
        raise SystemExit('Invalid .sdkmod layout: ' + ', '.join(e.name for e in entries))
    print(f'{target} ({len(files)} files)')
    return target


if __name__ == '__main__':
    sys.exit(0 if build() else 1)
