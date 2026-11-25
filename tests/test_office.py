from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation

from app.applications import office as office_module
from app.applications.office import OfficeDocumentService


def test_word_workbook_and_presentation_are_created_and_verified(tmp_path):
    service = OfficeDocumentService(tmp_path / "exports")
    word = service.create_word("report", "Monthly Report", ["Summary"], approved=True)
    workbook = service.create_excel(
        "expenses",
        {"Expenses": [["Category", "Amount"], ["Food", 25], ["Total", "=SUM(B2:B2)"]]},
        approved=True,
    )
    slides = service.create_powerpoint(
        "briefing",
        [{"title": "Results", "bullets": ["One", "Two"]}],
        approved=True,
    )

    assert [paragraph.text for paragraph in Document(word).paragraphs] == [
        "Monthly Report",
        "Summary",
    ]
    check = load_workbook(workbook, data_only=False)
    assert check.sheetnames == ["Expenses"]
    assert [
        [cell.value for cell in row]
        for row in check["Expenses"].iter_rows(min_row=1, max_row=3, max_col=2)
    ] == [
        ["Category", "Amount"],
        ["Food", 25],
        ["Total", "=SUM(B2:B2)"],
    ]
    check.close()
    presentation = Presentation(slides)
    slide = presentation.slides[0]
    assert slide.shapes.title.text == "Results"
    assert [paragraph.text for paragraph in slide.placeholders[1].text_frame.paragraphs] == [
        "One",
        "Two",
    ]


def test_excel_verification_rejects_wrong_saved_cell_and_cleans_temporary_file(
    tmp_path, monkeypatch
):
    service = OfficeDocumentService(tmp_path / "exports")
    original_save = office_module.Workbook.save
    corrupt_first_save = True

    def save_with_corrupted_cell(workbook, path):
        nonlocal corrupt_first_save
        original_save(workbook, path)
        if corrupt_first_save:
            corrupt_first_save = False
            corrupted = load_workbook(path, data_only=False)
            corrupted.active["A1"] = "corrupted"
            original_save(corrupted, path)
            corrupted.close()

    monkeypatch.setattr(office_module.Workbook, "save", save_with_corrupted_cell)
    with pytest.raises(IOError, match="cell values differ"):
        service.create_excel("incorrect.xlsx", {"Data": [["expected"]]}, approved=True)

    assert not (service.export_dir / "incorrect.xlsx").exists()
    assert not list(service.export_dir.glob(".shu-revision-*.xlsx"))


def test_document_creation_needs_approval_and_refuses_overwrite(tmp_path):
    service = OfficeDocumentService(tmp_path / "exports")
    with pytest.raises(PermissionError):
        service.create_word("report.docx", "Title", [], approved=False)
    created = service.create_word("report.docx", "Title", [], approved=True)
    with pytest.raises(FileExistsError):
        service.create_word("report.docx", "Second", [], approved=True)
    assert created.exists()


def test_path_traversal_and_untrusted_excel_formulas_are_safe(tmp_path):
    service = OfficeDocumentService(tmp_path / "exports")
    with pytest.raises(ValueError):
        service.create_word("..\\outside.docx", "Title", [], approved=True)
    assert service._safe_cell_value("=WEBSERVICE(\"https://bad.example\")").startswith("'")
    assert service._safe_cell_value("=SUM(A1:A2)") == "=SUM(A1:A2)"


def test_existing_office_files_can_be_revised_into_new_verified_copies(tmp_path):
    service = OfficeDocumentService(tmp_path / "exports")
    word_source = service.create_word("source.docx", "Original", ["Keep me"], approved=True)
    excel_source = service.create_excel(
        "source.xlsx", {"Data": [["Item", "Count"], ["Books", 2]]}, approved=True
    )
    ppt_source = service.create_powerpoint(
        "source.pptx", [{"title": "Original slide", "bullets": ["Keep me"]}], approved=True
    )

    word_revision = service.create_word_revision(
        word_source.name, "source-revised", ["Added paragraph"], approved=True
    )
    excel_revision = service.create_excel_revision(
        excel_source.name,
        "source-revised",
        [{"sheet": "Data", "cell": "B2", "value": 3}],
        approved=True,
    )
    ppt_revision = service.create_powerpoint_revision(
        ppt_source.name,
        "source-revised",
        [{"title": "New slide", "bullets": ["Added after original"]}],
        approved=True,
    )

    assert [p.text for p in Document(word_source).paragraphs] == ["Original", "Keep me"]
    assert [p.text for p in Document(word_revision).paragraphs][-1] == "Added paragraph"
    source_workbook = load_workbook(excel_source, data_only=False)
    revised_workbook = load_workbook(excel_revision, data_only=False)
    assert source_workbook["Data"]["B2"].value == 2
    assert revised_workbook["Data"]["B2"].value == 3
    source_workbook.close()
    revised_workbook.close()
    assert len(Presentation(ppt_source).slides) == 1
    revised_presentation = Presentation(ppt_revision)
    assert len(revised_presentation.slides) == 2
    assert revised_presentation.slides[-1].shapes.title.text == "New slide"


def test_office_revision_requires_approval_and_never_overwrites_source(tmp_path):
    service = OfficeDocumentService(tmp_path / "exports")
    source = service.create_word("original.docx", "Original", ["Keep"], approved=True)
    with pytest.raises(PermissionError, match="explicit approval"):
        service.create_word_revision(source.name, "copy.docx", ["New"], approved=False)
    with pytest.raises(ValueError, match="new output filename"):
        service.create_word_revision(source.name, source.name, ["New"], approved=True)
    with pytest.raises(FileExistsError):
        service.create_word_revision(source.name, "copy.docx", ["First"], approved=True)
        service.create_word_revision(source.name, "copy.docx", ["Second"], approved=True)


@pytest.mark.parametrize("kind", ["word", "excel", "powerpoint"])
def test_pdf_export_uses_read_only_office_automation_and_keeps_source(tmp_path, monkeypatch, kind):
    export_dir = tmp_path / "exports"
    service = OfficeDocumentService(export_dir)
    if kind == "word":
        source = service.create_word("report.docx", "Report", ["Private source"], approved=True)
        program_id = "Word.Application"
        opener_name = "Documents"
    elif kind == "excel":
        source = service.create_excel("report.xlsx", {"Sheet1": [["Private source"]]}, approved=True)
        program_id = "Excel.Application"
        opener_name = "Workbooks"
    else:
        source = service.create_powerpoint(
            "report.pptx", [{"title": "Private source", "bullets": []}], approved=True
        )
        program_id = "PowerPoint.Application"
        opener_name = "Presentations"

    class FakeOfficeDocument:
        def __init__(self):
            self.Slides = SimpleNamespace(Count=1)
            self.ExportAsFixedFormat = Mock(side_effect=self._export)

        @staticmethod
        def _export(*args):
            output = args[1] if args and isinstance(args[0], int) else args[0]
            Path(output).write_bytes(b"%PDF-" + b"x" * 200)

        def Close(self, *args, **kwargs):
            pass

    office_document = FakeOfficeDocument()
    opener = Mock(return_value=office_document)
    application = SimpleNamespace(
        Documents=SimpleNamespace(Open=opener),
        Workbooks=SimpleNamespace(Open=opener),
        Presentations=SimpleNamespace(Open=opener),
        Quit=Mock(),
    )
    dispatch = Mock(return_value=application)
    pythoncom = ModuleType("pythoncom")
    pythoncom.CoInitialize = Mock()
    pythoncom.CoUninitialize = Mock()
    monkeypatch.setitem(__import__("sys").modules, "pythoncom", pythoncom)

    office_service = OfficeDocumentService(export_dir, com_dispatcher=dispatch)
    with pytest.raises(PermissionError, match="explicit approval"):
        office_service.export_pdf(source.name, approved=False)
    dispatch.assert_not_called()
    pdf = office_service.export_pdf(source.name, approved=True)

    assert dispatch.call_args.args == (program_id,)
    assert opener.call_args.kwargs["ReadOnly"] is True
    assert pdf.name == "report.pdf"
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert source.is_file()
    application.Quit.assert_called_once()
    pythoncom.CoUninitialize.assert_called_once()
    assert getattr(application, opener_name) is not None
    if kind == "powerpoint":
        assert office_document.ExportAsFixedFormat.call_args.args[7] is None
        assert office_document.ExportAsFixedFormat.call_args.args[8] == 1
