import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.voice.language_config import SUPPORTED_LANGUAGES


def main() -> None:
    print("SHU Supported Languages")
    for name, code in SUPPORTED_LANGUAGES.items():
        print(f"{name}: {code}")

    assert len(SUPPORTED_LANGUAGES) == 6
    print("\nAll 6 Languages Configured Successfully!")


if __name__ == "__main__":
    main()
