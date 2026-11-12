from getpass import getpass
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / ".env"
NAMES = (
    "HEADCOUNTLABS_API_KEY",
    "ADZUNA_APP_ID",
    "ADZUNA_APP_KEY",
    "SUPERJOB_APP_SECRET",
)


def main():
    current = {}
    if TARGET.exists():
        for line in TARGET.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                current[key] = value
    values = {}
    for name in NAMES:
        value = getpass(f"{name} (Enter keeps existing value): ")
        values[name] = value or current.get(name, "")
    missing = [name for name, value in values.items() if not value]
    TARGET.write_text("".join(f"{name}={values[name]}\n" for name in NAMES))
    os.chmod(TARGET, 0o600)
    print(f"Saved locally to {TARGET}; values were not echoed.")
    if missing:
        print("Still missing: " + ", ".join(missing))


if __name__ == "__main__":
    main()
