from __future__ import annotations

import argparse
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def collect_log_files(base_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in base_dir.glob('*.log')
        if path.is_file()
    )


def create_log_archive(base_dir: Path, output_name: str = 'build.zip', delete_logs: bool = True) -> Path:
    log_files = collect_log_files(base_dir)
    output_path = base_dir / output_name

    if output_path.exists():
        output_path.unlink()

    with ZipFile(output_path, mode='w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for log_file in log_files:
            archive.write(log_file, arcname=log_file.name)

    if delete_logs:
        for log_file in log_files:
            log_file.unlink()

    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Archive *.log files into a zip file.')
    parser.add_argument('--base-dir', default='.', help='Directory containing *.log files.')
    parser.add_argument('--output', default='build.zip', help='Archive filename to create.')
    parser.add_argument(
        '--keep-logs',
        action='store_true',
        help='Keep the original log files after creating the archive.',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base_dir = Path(args.base_dir).resolve()
    create_log_archive(base_dir=base_dir, output_name=args.output, delete_logs=not args.keep_logs)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
