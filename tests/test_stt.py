import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.voice.stt_engine import SHUSTTEngine
from app.voice.language_config import SUPPORTED_LANGUAGES


def main() -> None:
    print("==============================")
    print("   SHU MULTILINGUAL STT TEST")
    print("==============================")

    print("\nAvailable Languages:")
    for index, language in enumerate(SUPPORTED_LANGUAGES.keys(), start=1):
        print(f"{index}. {language}")

    choice = input("\nSelect Language (1-6): ")
    try:
        language = list(SUPPORTED_LANGUAGES.keys())[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid language selection!")
        return

    shu = SHUSTTEngine(
        model_size="small",
        device_index=1,
    )
    result = shu.listen_and_transcribe(
        duration=5,
        language=language,
    )

    print("\n========== TEST RESULT ==========")
    print("Text:", result["text"])
    print("Language:", result["language"])
    print("Probability:", result["language_probability"])
    print("\nSHU Multilingual STT Test Completed!")


if __name__ == "__main__":
    main()
