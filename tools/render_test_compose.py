from __future__ import annotations

import argparse
from pathlib import Path

SERVICES_WITHOUT_HOST_PORTS = {
    "api-test",
    "web-ui-test",
    "db",
    "redis",
    "minio",
    "llm-fake",
}


def strip_ports_for_services(text: str, service_names: set[str]) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_services = False
    current_service: str | None = None
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if not in_services:
            out.append(line)
            if stripped == "services:":
                in_services = True
            i += 1
            continue

        if indent == 2 and stripped.endswith(":") and not stripped.startswith("#"):
            current_service = stripped[:-1]
            out.append(line)
            i += 1
            continue

        if current_service in service_names and indent == 4 and stripped == "ports:":
            i += 1
            while i < len(lines):
                next_line = lines[i]
                next_indent = len(next_line) - len(next_line.lstrip(" "))
                next_stripped = next_line.strip()
                if next_line and next_indent <= 4 and next_stripped:
                    break
                i += 1
            continue

        out.append(line)
        i += 1

    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    args = parser.parse_args()

    source = Path(args.input_path)
    destination = Path(args.output_path)
    rendered = strip_ports_for_services(source.read_text(encoding="utf-8"), SERVICES_WITHOUT_HOST_PORTS)
    destination.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
