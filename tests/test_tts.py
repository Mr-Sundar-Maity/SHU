import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.voice.tts_engine import SHUTTSEngine


def main() -> None:
    print("==============================")
    print("       SHU TTS TEST")
    print("==============================")

    shu = SHUTTSEngine(voice="en-US-GuyNeural")
    shu.speak(
        "Hello! I am SHU, your personal AI assistant. "
        "It is nice to meet you."
    )

    print("\nSHU TTS Test Completed!")


if __name__ == "__main__":
    main()
