import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.ai_engine import SHUAIEngine


def main() -> None:
    print("==============================")
    print("       SHU AI BRAIN TEST")
    print("==============================")

    shu = SHUAIEngine()
    question = "Hello SHU! Introduce yourself."
    print("\nYou:", question)
    response = shu.ask(question, provider="ollama")
    print("\nSHU:", response)
    print("\nSHU AI Test Completed!")


if __name__ == "__main__":
    main()
