"""Package tracked public files and a dedicated Windows runtime into a release ZIP."""
import argparse
import ast
from pathlib import Path
import subprocess
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('dist'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    runtime = args.runtime.resolve()
    if not (runtime / 'python.exe').is_file() or not (runtime / 'python310._pth').is_file():
        parser.error('Expected the isolated Python 3.10 Windows runtime.')
    tree = ast.parse((root / 'processore_immagini.py').read_text(encoding='utf-8-sig'))
    version = next(node.value.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in node.targets))
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0')
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / f'AI-Visual-Editor-v{version}-Windows-Portable.zip'
    prefix = 'AI-Visual-Editor/'
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            if name:
                archive.write(root / name, prefix + name)
        for path in sorted(runtime.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                archive.write(path, prefix + 'runtime/' + path.relative_to(runtime).as_posix())
    print(output.resolve())


if __name__ == '__main__':
    main()
