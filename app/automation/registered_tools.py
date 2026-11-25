"""Built-in safe tools registered through SHU's policy layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from app.automation.windows import WindowsAutomation
from app.security.policy import RiskLevel
from app.security.registry import ToolRegistry, ToolSpec


def _only_keys(allowed: set[str]):
    def validate(arguments: Mapping[str, Any]) -> dict[str, Any]:
        if set(arguments) != allowed:
            raise ValueError("Tool arguments do not match the registered schema")
        result = dict(arguments)
        for key in allowed:
            if not isinstance(result[key], str) or len(result[key]) > 2_000:
                raise TypeError(f"{key} must be text of at most 2000 characters")
        return result
    return validate


def _no_args(arguments: Mapping[str, Any]) -> dict[str, Any]:
    if arguments:
        raise ValueError("This tool does not accept arguments")
    return {}


def _office_tools(registry: ToolRegistry, service) -> None:
    def word_args(args: Mapping[str, Any]) -> dict[str, Any]:
        if set(args) != {"filename", "title", "paragraphs"}:
            raise ValueError("Word tool requires filename, title, and paragraphs")
        if not all(isinstance(args[k], str) for k in ("filename", "title")):
            raise TypeError("Word filename and title must be text")
        paragraphs = args["paragraphs"]
        if not isinstance(paragraphs, list) or len(paragraphs) > 500 or not all(isinstance(x, str) for x in paragraphs):
            raise TypeError("Word paragraphs must be a list of at most 500 text items")
        return {"filename": args["filename"], "title": args["title"], "paragraphs": paragraphs}

    def excel_args(args: Mapping[str, Any]) -> dict[str, Any]:
        if set(args) != {"filename", "sheets"} or not isinstance(args["filename"], str) or not isinstance(args["sheets"], dict):
            raise ValueError("Excel tool requires filename and a sheet mapping")
        if len(args["sheets"]) > 30:
            raise ValueError("Workbook cannot exceed 30 sheets")
        return {"filename": args["filename"], "sheets": args["sheets"]}

    def ppt_args(args: Mapping[str, Any]) -> dict[str, Any]:
        if set(args) != {"filename", "slides"} or not isinstance(args["filename"], str) or not isinstance(args["slides"], list):
            raise ValueError("PowerPoint tool requires filename and slides")
        if len(args["slides"]) > 100:
            raise ValueError("Presentation cannot exceed 100 slides")
        return {"filename": args["filename"], "slides": args["slides"]}

    def word_revision_args(args: Mapping[str, Any]) -> dict[str, Any]:
        if set(args) != {"source_filename", "output_filename", "paragraphs"}:
            raise ValueError("Word revision requires source_filename, output_filename and paragraphs")
        if not all(isinstance(args[key], str) for key in ("source_filename", "output_filename")):
            raise TypeError("Word revision filenames must be text")
        paragraphs = args["paragraphs"]
        if not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= 500:
            raise ValueError("Word revision needs 1-500 paragraphs")
        if not all(isinstance(item, str) and item.strip() for item in paragraphs):
            raise TypeError("Word revision paragraphs must be non-empty text")
        return dict(args)

    def excel_revision_args(args: Mapping[str, Any]) -> dict[str, Any]:
        if set(args) != {"source_filename", "output_filename", "updates"}:
            raise ValueError("Excel revision requires source_filename, output_filename and updates")
        if not all(isinstance(args[key], str) for key in ("source_filename", "output_filename")):
            raise TypeError("Excel revision filenames must be text")
        updates = args["updates"]
        if not isinstance(updates, list) or not 1 <= len(updates) <= 500:
            raise ValueError("Excel revision needs 1-500 updates")
        for item in updates:
            if not isinstance(item, dict) or set(item) != {"sheet", "cell", "value"}:
                raise ValueError("Each Excel update needs sheet, cell and value")
            if not isinstance(item["sheet"], str) or not isinstance(item["cell"], str):
                raise TypeError("Excel sheet and cell names must be text")
            if not isinstance(item["value"], (str, int, float, bool, type(None))):
                raise TypeError("Excel values must be scalar text, number, boolean or null")
        return dict(args)

    def ppt_revision_args(args: Mapping[str, Any]) -> dict[str, Any]:
        if set(args) != {"source_filename", "output_filename", "slides"}:
            raise ValueError("PowerPoint revision requires source_filename, output_filename and slides")
        if not all(isinstance(args[key], str) for key in ("source_filename", "output_filename")):
            raise TypeError("PowerPoint revision filenames must be text")
        if not isinstance(args["slides"], list) or not 1 <= len(args["slides"]) <= 100:
            raise ValueError("PowerPoint revision needs 1-100 slides")
        return dict(args)

    registry.register(ToolSpec(
        "create_word_document", "Create and verify a Word document", RiskLevel.MODIFICATION,
        lambda **kwargs: service.create_word(**kwargs, approved=True), word_args,
        lambda result, _args: Path(result).is_file() and Path(result).stat().st_size > 0,
        estimate_seconds=30, resources=("filesystem", "office_com"),
    ))
    registry.register(ToolSpec(
        "create_excel_workbook", "Create and verify an Excel workbook", RiskLevel.MODIFICATION,
        lambda **kwargs: service.create_excel(**kwargs, approved=True), excel_args,
        lambda result, _args: Path(result).is_file() and Path(result).stat().st_size > 0,
        estimate_seconds=30, resources=("filesystem", "office_com"),
    ))
    registry.register(ToolSpec(
        "create_powerpoint", "Create and verify a PowerPoint presentation", RiskLevel.MODIFICATION,
        lambda **kwargs: service.create_powerpoint(**kwargs, approved=True), ppt_args,
        lambda result, _args: Path(result).is_file() and Path(result).stat().st_size > 0,
        estimate_seconds=45, resources=("filesystem", "office_com"),
    ))
    registry.register(ToolSpec(
        "revise_word_copy", "Append text to a new copy of an existing Word file", RiskLevel.MODIFICATION,
        lambda **kwargs: service.create_word_revision(**kwargs, approved=True), word_revision_args,
        lambda result, _args: Path(result).is_file() and Path(result).stat().st_size > 0,
        estimate_seconds=30, resources=("filesystem", "office_com"),
    ))
    registry.register(ToolSpec(
        "revise_excel_copy", "Update cells in a new copy of an existing workbook", RiskLevel.MODIFICATION,
        lambda **kwargs: service.create_excel_revision(**kwargs, approved=True), excel_revision_args,
        lambda result, _args: Path(result).is_file() and Path(result).stat().st_size > 0,
        estimate_seconds=30, resources=("filesystem", "office_com"),
    ))
    registry.register(ToolSpec(
        "revise_powerpoint_copy", "Append slides to a new copy of an existing presentation", RiskLevel.MODIFICATION,
        lambda **kwargs: service.create_powerpoint_revision(**kwargs, approved=True), ppt_revision_args,
        lambda result, _args: Path(result).is_file() and Path(result).stat().st_size > 0,
        estimate_seconds=45, resources=("filesystem", "office_com"),
    ))
    registry.register(ToolSpec(
        "export_office_pdf", "Export an Office file as PDF without changing the source", RiskLevel.MODIFICATION,
        lambda **kwargs: service.export_pdf(**kwargs, approved=True),
        _only_keys({"source_filename"}),
        lambda result, _args: Path(result).is_file()
        and Path(result).read_bytes().startswith(b"%PDF-"),
        estimate_seconds=20, resources=("filesystem", "office_com"),
    ))


def _uia_tools(registry: ToolRegistry, automation: WindowsAutomation) -> None:
    def fill_args(args: Mapping[str, Any]) -> dict[str, str]:
        required = {"window_title", "control_name", "text"}
        if set(args) != required or not all(isinstance(args[key], str) for key in required):
            raise ValueError("UIA text fill requires window_title, control_name and text")
        result = dict(args)
        if not result["window_title"].strip() or len(result["window_title"]) > 300:
            raise ValueError("Window title must contain 1-300 characters")
        if not result["control_name"].strip() or len(result["control_name"]) > 200:
            raise ValueError("Control name must contain 1-200 characters")
        if not result["text"] or len(result["text"]) > 2_000:
            raise ValueError("Text must contain 1-2000 characters")
        return result

    def click_args(args: Mapping[str, Any]) -> dict[str, str]:
        required = {"window_title", "control_name", "expected_state"}
        if set(args) != required or not all(isinstance(args[key], str) for key in required):
            raise ValueError(
                "Desktop click requires window_title, control_name and expected_state"
            )
        result = dict(args)
        if not result["window_title"].strip() or len(result["window_title"]) > 300:
            raise ValueError("Window title must contain 1-300 characters")
        if not result["control_name"].strip() or len(result["control_name"]) > 200:
            raise ValueError("Control name must contain 1-200 characters")
        if result["expected_state"] not in WindowsAutomation.CLICK_EXPECTED_STATES:
            raise ValueError("Desktop click needs a supported, verifiable expected_state")
        return result

    def screen_args(args: Mapping[str, Any]) -> dict[str, int]:
        required = {"left", "top", "width", "height"}
        if set(args) != required:
            raise ValueError("Screen OCR requires left, top, width and height")
        if any(isinstance(args[key], bool) or not isinstance(args[key], int) for key in required):
            raise TypeError("Screen region coordinates must be integers")
        result = dict(args)
        if (
            result["left"] < 0
            or result["top"] < 0
            or result["width"] < 1
            or result["height"] < 1
            or result["width"] * result["height"] > 8_294_400
        ):
            raise ValueError("Screen region is invalid or exceeds the 4K pixel limit")
        return result

    registry.register(
        ToolSpec(
            name="inspect_window_controls",
            description="Inspect visible UI Automation control names and types",
            risk=RiskLevel.READ_ONLY,
            handler=automation.inspect_window,
            validator=_only_keys({"title"}),
            estimate_seconds=4,
            resources=("desktop_access",),
        )
    )
    registry.register(
        ToolSpec(
            name="fill_empty_text_control",
            description="Prepare a visible empty non-password text field; never submit",
            risk=RiskLevel.MODIFICATION,
            handler=automation.fill_empty_text_control,
            validator=fill_args,
            verifier=lambda result, _args: bool(
                isinstance(result, dict)
                and result.get("verified") is True
                and result.get("submitted") is False
            ),
            estimate_seconds=5,
            resources=("desktop_input",),
        )
    )
    registry.register(
        ToolSpec(
            name="click_visible_control",
            description=(
                "After approval, click one unique visible control and verify expected_state "
                "(checked, unchecked, selected, unselected, hidden or disabled)"
            ),
            risk=RiskLevel.EXTERNAL_ACTION,
            handler=lambda window_title, control_name, expected_state: automation.click_visible_control(
                window_title,
                control_name,
                expected_state,
                approved=True,
            ),
            validator=click_args,
            requires_approval=True,
            verifier=lambda result, _args: bool(
                isinstance(result, dict)
                and result.get("postcondition_verified") is True
            ),
            estimate_seconds=3,
            resources=("desktop_input",),
        )
    )
    registry.register(
        ToolSpec(
            name="read_screen_text",
            description="Capture a selected screen rectangle and OCR it locally",
            risk=RiskLevel.READ_ONLY,
            handler=automation.read_screen_text,
            validator=screen_args,
            requires_approval=True,
            estimate_seconds=8,
            resources=("desktop_capture", "ocr"),
        )
    )


def register_safe_desktop_tools(
    registry: ToolRegistry,
    automation: WindowsAutomation,
    office_service=None,
) -> None:
    copy_keys = _only_keys({"source", "destination", "expected_sha256"})
    registry.register(
        ToolSpec(
            name="list_allowed_files",
            description="List file names in an approved SHU directory",
            risk=RiskLevel.READ_ONLY,
            handler=automation.list_allowed_files,
            validator=_only_keys({"directory"}),
            estimate_seconds=3,
            resources=("filesystem",),
        )
    )
    registry.register(
        ToolSpec(
            name="preview_allowed_file",
            description="Show the path, size and SHA-256 of a file in an approved SHU directory",
            risk=RiskLevel.READ_ONLY,
            handler=automation.preview_allowed_file,
            validator=_only_keys({"path"}),
            estimate_seconds=3,
            resources=("filesystem",),
        )
    )
    registry.register(
        ToolSpec(
            name="copy_allowed_file",
            description="Copy an approved file to an unused path using its previewed SHA-256",
            risk=RiskLevel.MODIFICATION,
            handler=lambda **arguments: automation.copy_allowed_file(**arguments, approved=True),
            validator=lambda args: automation.validate_copy_arguments(**copy_keys(args)),
            verifier=lambda result, args: (
                result["destination"] == args["destination"]
                and result["sha256"] == args["expected_sha256"]
            ),
            estimate_seconds=5,
            resources=("filesystem",),
        )
    )
    registry.register(
        ToolSpec(
            name="list_windows",
            description="List visible Windows application titles",
            risk=RiskLevel.READ_ONLY,
            handler=automation.list_windows,
            validator=_no_args,
            estimate_seconds=3,
            resources=("desktop_access",),
        )
    )
    registry.register(
        ToolSpec(
            name="launch_application",
            description="Open an allowlisted application",
            risk=RiskLevel.LOW_IMPACT,
            handler=automation.launch_application,
            validator=_only_keys({"app_id"}),
            estimate_seconds=5,
            resources=("desktop_access", "process"),
        )
    )
    _uia_tools(registry, automation)
    if office_service is not None:
        _office_tools(registry, office_service)
