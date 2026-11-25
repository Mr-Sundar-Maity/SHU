import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.voice.voice_assistant import SHUVoiceAssistant


def main() -> None:
    print("==============================")
    print("     SHU VOICE INTEGRATION")
    print("==============================")

    assistant = SHUVoiceAssistant()
    assistant.start()

    print("\nSHU Voice Integration Test Completed!")


if __name__ == "__main__":
    main()
