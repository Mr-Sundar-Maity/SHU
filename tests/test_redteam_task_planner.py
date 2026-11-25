import ast
from pathlib import Path


def test_planner_red_team_corpus_has_unique_multilingual_attack_families():
    script = Path(__file__).resolve().parents[1] / "scripts" / "redteam_task_planner.py"
    module = ast.parse(script.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CASES" for target in node.targets)
    )
    cases = ast.literal_eval(assignment.value)

    labels = [label for label, _prompt in cases]
    required_families = {
        "telugu_page_instruction_injection",
        "malayalam_page_instruction_injection",
        "zero_width_character_instruction_injection",
        "html_attribute_instruction_injection",
        "yaml_frontmatter_instruction_injection",
        "filename_instruction_injection",
        "fake_confirmation_token_instruction_injection",
    }

    assert len(cases) == 30
    assert len(set(labels)) == len(labels)
    assert required_families.issubset(labels)
    assert all(isinstance(prompt, str) and prompt.strip() for _, prompt in cases)
