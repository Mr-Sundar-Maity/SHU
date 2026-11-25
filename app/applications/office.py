"""Verified Word, Excel and PowerPoint file generation in an export allowlist."""

from __future__ import annotations

import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from docx import Document
from openpyxl import Workbook, load_workbook
from pptx import Presentation
from pptx.util import Inches, Pt

from app.automation.paths import PathPolicy


_SAFE_FORMULA = re.compile(
    r"^=(?:SUM|AVERAGE|MIN|MAX|COUNT|COUNTA)\("
    r"\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?"
    r"(?:,\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)*\)$",
    re.IGNORECASE,
)
_MAX_EXCEL_CELLS = 250_000


class OfficeDocumentService:
    def __init__(self, export_dir: str | Path, *, com_dispatcher=None) -> None:
        self.export_dir = Path(export_dir).expanduser().resolve()
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.paths = PathPolicy([self.export_dir])
        self.com_dispatcher = com_dispatcher

    def create_word(
        self,
        filename: str,
        title: str,
        paragraphs: list[str],
        *,
        approved: bool = False,
    ) -> Path:
        self._require_approval(approved)
        filename = self._filename(filename, ".docx")
        if not title.strip() or len(paragraphs) > 500:
            raise ValueError("A title is required and no more than 500 paragraphs are allowed")
        target = self.paths.resolve(self.export_dir / filename)
        self._refuse_overwrite(target)
        expected_paragraphs = [str(paragraph)[:20_000] for paragraph in paragraphs]
        document = Document()
        document.add_heading(title.strip(), level=0)
        for paragraph in expected_paragraphs:
            document.add_paragraph(paragraph)

        def verify(path: Path) -> None:
            actual = [paragraph.text for paragraph in Document(path).paragraphs]
            if actual != [title.strip(), *expected_paragraphs]:
                raise IOError("Word document verification failed")

        return self._save_verified_output(target, document.save, verify)

    def create_excel(
        self,
        filename: str,
        sheets: dict[str, list[list[Any]]],
        *,
        approved: bool = False,
    ) -> Path:
        self._require_approval(approved)
        filename = self._filename(filename, ".xlsx")
        if not isinstance(sheets, dict) or not sheets or len(sheets) > 30:
            raise ValueError("Workbook needs between 1 and 30 sheets")
        target = self.paths.resolve(self.export_dir / filename)
        self._refuse_overwrite(target)

        workbook = Workbook()
        default_sheet = workbook.active
        workbook.remove(default_sheet)
        expected_sheets: dict[str, list[list[Any]]] = {}
        total_cells = 0
        for name, rows in sheets.items():
            if not isinstance(name, str) or not isinstance(rows, (list, tuple)):
                raise TypeError("Sheet names must be text and sheet rows must be a list")
            safe_name = name.strip()
            if (
                not safe_name
                or len(safe_name) > 31
                or any(character in safe_name for character in "\\/*?:[]")
                or safe_name.startswith("'")
                or safe_name.endswith("'")
                or safe_name.casefold() in {item.casefold() for item in workbook.sheetnames}
            ):
                raise ValueError("Sheet names must be valid, non-empty and unique")
            if len(rows) > 20_000:
                raise ValueError("A worksheet cannot exceed 20000 rows")
            worksheet = workbook.create_sheet(safe_name)
            expected_rows: list[list[Any]] = []
            for row in rows:
                if not isinstance(row, (list, tuple)) or len(row) > 200:
                    raise ValueError("Each row must contain at most 200 cells")
                safe_row = [self._safe_cell_value(value) for value in row]
                total_cells += len(safe_row)
                if total_cells > _MAX_EXCEL_CELLS:
                    raise ValueError(
                        f"Workbook cannot exceed {_MAX_EXCEL_CELLS} cells"
                    )
                worksheet.append(safe_row)
                expected_rows.append(safe_row)
            expected_sheets[safe_name] = expected_rows

        def verify(path: Path) -> None:
            verified = load_workbook(path, read_only=True, data_only=False)
            try:
                if verified.sheetnames != list(expected_sheets):
                    raise IOError("Workbook verification failed: sheet names differ")
                for sheet_name, rows in expected_sheets.items():
                    worksheet = verified[sheet_name]
                    for row_index, expected_row in enumerate(rows, start=1):
                        for column_index, expected_value in enumerate(expected_row, start=1):
                            if worksheet.cell(row_index, column_index).value != expected_value:
                                raise IOError("Workbook verification failed: cell values differ")
            finally:
                verified.close()

        return self._save_verified_output(target, workbook.save, verify)

    def create_powerpoint(
        self,
        filename: str,
        slides: list[dict[str, Any]],
        *,
        approved: bool = False,
    ) -> Path:
        self._require_approval(approved)
        filename = self._filename(filename, ".pptx")
        if not slides or len(slides) > 100:
            raise ValueError("Presentation needs between 1 and 100 slides")
        target = self.paths.resolve(self.export_dir / filename)
        self._refuse_overwrite(target)

        presentation = Presentation()
        expected_slides: list[tuple[str, list[str]]] = []
        for slide_data in slides:
            if not isinstance(slide_data, dict):
                raise ValueError("Each slide must be an object")
            title = str(slide_data.get("title", "")).strip()
            bullets = slide_data.get("bullets", [])
            if not title or not isinstance(bullets, list) or len(bullets) > 20:
                raise ValueError("Each slide needs a title and no more than 20 bullets")
            expected_title = title[:200]
            expected_bullets = [str(bullet)[:2_000] for bullet in bullets]
            slide = presentation.slides.add_slide(presentation.slide_layouts[1])
            slide.shapes.title.text = expected_title
            body = slide.placeholders[1].text_frame
            body.clear()
            for index, bullet in enumerate(expected_bullets):
                paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
                paragraph.text = bullet
                paragraph.font.size = Pt(20)
            expected_slides.append((expected_title, expected_bullets))

        def verify(path: Path) -> None:
            verified = Presentation(path)
            if len(verified.slides) != len(expected_slides):
                raise IOError("PowerPoint verification failed: slide count differs")
            for slide, (expected_title, expected_bullets) in zip(
                verified.slides, expected_slides, strict=True
            ):
                actual_title = slide.shapes.title.text if slide.shapes.title else ""
                body = slide.placeholders[1].text_frame
                actual_bullets = [paragraph.text for paragraph in body.paragraphs]
                if not expected_bullets and actual_bullets == [""]:
                    actual_bullets = []
                if actual_title != expected_title or actual_bullets != expected_bullets:
                    raise IOError("PowerPoint verification failed: slide content differs")

        return self._save_verified_output(target, presentation.save, verify)

    def create_word_revision(
        self,
        source_filename: str,
        output_filename: str,
        paragraphs: list[str],
        *,
        approved: bool = False,
    ) -> Path:
        """Append paragraphs to an existing DOCX and save as a new verified copy."""
        self._require_approval(approved)
        if not paragraphs or len(paragraphs) > 500 or not all(
            isinstance(item, str) and item.strip() for item in paragraphs
        ):
            raise ValueError("A revision needs 1-500 non-empty paragraphs")
        source = self._source_path(source_filename, ".docx")
        target = self._revision_target(source, output_filename, ".docx")
        document = Document(source)
        original_paragraphs = [paragraph.text for paragraph in document.paragraphs]
        expected = [item[:20_000] for item in paragraphs]
        for paragraph in expected:
            document.add_paragraph(paragraph)

        def verify(path: Path) -> None:
            revised = Document(path)
            actual = [paragraph.text for paragraph in revised.paragraphs]
            if actual != [*original_paragraphs, *expected]:
                raise IOError("Word revision verification failed")

        return self._save_verified_output(target, document.save, verify)

    def create_excel_revision(
        self,
        source_filename: str,
        output_filename: str,
        updates: list[dict[str, Any]],
        *,
        approved: bool = False,
    ) -> Path:
        """Apply bounded cell updates to a new copy of an existing XLSX workbook."""
        self._require_approval(approved)
        if not updates or len(updates) > 500:
            raise ValueError("An Excel revision needs 1-500 cell updates")
        source = self._source_path(source_filename, ".xlsx")
        target = self._revision_target(source, output_filename, ".xlsx")
        workbook = load_workbook(source, read_only=False, data_only=False)
        expected: list[tuple[str, str, Any]] = []
        seen: set[tuple[str, str]] = set()
        try:
            for update in updates:
                if not isinstance(update, dict) or set(update) != {"sheet", "cell", "value"}:
                    raise ValueError("Each Excel update needs sheet, cell and value")
                sheet_name = update["sheet"]
                cell_name = update["cell"]
                if not isinstance(sheet_name, str) or sheet_name not in workbook.sheetnames:
                    raise ValueError("Excel updates must name an existing worksheet")
                if not isinstance(cell_name, str) or not re.fullmatch(
                    r"[A-Za-z]{1,3}[1-9][0-9]{0,6}", cell_name
                ):
                    raise ValueError("Excel cell address is invalid")
                coordinate = cell_name.upper()
                key = (sheet_name, coordinate)
                if key in seen:
                    raise ValueError("An Excel revision cannot update the same cell twice")
                seen.add(key)
                value = self._safe_cell_value(update["value"])
                workbook[sheet_name][coordinate] = value
                expected.append((sheet_name, coordinate, value))

            def save(path: Path) -> None:
                workbook.save(path)

            def verify(path: Path) -> None:
                revised = load_workbook(path, read_only=True, data_only=False)
                try:
                    for sheet_name, coordinate, value in expected:
                        if revised[sheet_name][coordinate].value != value:
                            raise IOError("Excel revision verification failed")
                finally:
                    revised.close()

            return self._save_verified_output(target, save, verify)
        finally:
            workbook.close()

    def create_powerpoint_revision(
        self,
        source_filename: str,
        output_filename: str,
        slides: list[dict[str, Any]],
        *,
        approved: bool = False,
    ) -> Path:
        """Append slides to an existing PPTX and save as a new verified copy."""
        self._require_approval(approved)
        if not slides or len(slides) > 100:
            raise ValueError("A presentation revision needs 1-100 slides")
        source = self._source_path(source_filename, ".pptx")
        target = self._revision_target(source, output_filename, ".pptx")
        presentation = Presentation(source)
        starting_count = len(presentation.slides)
        original_slide_content = [
            self._slide_text_content(slide) for slide in presentation.slides
        ]
        expected_slides: list[tuple[str, list[str]]] = []
        for slide_data in slides:
            if not isinstance(slide_data, dict):
                raise ValueError("Each new slide must be an object")
            title = str(slide_data.get("title", "")).strip()
            bullets = slide_data.get("bullets", [])
            if not title or not isinstance(bullets, list) or len(bullets) > 20:
                raise ValueError("Each new slide needs a title and no more than 20 bullets")
            slide = presentation.slides.add_slide(presentation.slide_layouts[1])
            slide.shapes.title.text = title[:200]
            body = slide.placeholders[1].text_frame
            body.clear()
            for index, bullet in enumerate(bullets):
                paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
                paragraph.text = str(bullet)[:2_000]
                paragraph.font.size = Pt(20)
            expected_slides.append(
                (title[:200], [str(bullet)[:2_000] for bullet in bullets])
            )

        def verify(path: Path) -> None:
            revised = Presentation(path)
            if len(revised.slides) != starting_count + len(expected_slides):
                raise IOError("PowerPoint revision slide-count verification failed")
            for index, expected_content in enumerate(original_slide_content):
                if self._slide_text_content(revised.slides[index]) != expected_content:
                    raise IOError("PowerPoint revision changed existing slide content")
            for slide, (expected_title, expected_bullets) in zip(
                list(revised.slides)[starting_count:], expected_slides, strict=True
            ):
                actual_title = slide.shapes.title.text if slide.shapes.title else ""
                actual_bullets = [
                    paragraph.text for paragraph in slide.placeholders[1].text_frame.paragraphs
                ]
                if not expected_bullets and actual_bullets == [""]:
                    actual_bullets = []
                if actual_title != expected_title or actual_bullets != expected_bullets:
                    raise IOError("PowerPoint revision slide content verification failed")

        return self._save_verified_output(target, presentation.save, verify)

    def export_pdf(self, source_filename: str, *, approved: bool = False) -> Path:
        """Export an Office file to PDF in a new read-only Office process."""
        self._require_approval(approved)
        extension = Path(source_filename).suffix.lower()
        if extension not in {".docx", ".xlsx", ".pptx"}:
            raise ValueError("PDF export supports DOCX, XLSX and PPTX files")
        source = self._source_path(source_filename, extension)
        if source.stat().st_size > 100_000_000:
            raise ValueError("Office PDF export is limited to source files under 100 MB")
        target = self.paths.resolve(self.export_dir / f"{source.stem}.pdf")
        self._refuse_overwrite(target)

        descriptor, temp_name = tempfile.mkstemp(
            prefix=".shu-pdf-", suffix=".pdf", dir=self.export_dir
        )
        os.close(descriptor)
        temporary = Path(temp_name)
        temporary.unlink()

        try:
            import pythoncom

            pythoncom.CoInitialize()
        except ImportError as error:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("pywin32 is required for Office PDF export") from error

        app = document = None
        try:
            if self.com_dispatcher is None:
                import win32com.client

                dispatch = win32com.client.DispatchEx
            else:
                dispatch = self.com_dispatcher

            program_id = {
                ".docx": "Word.Application",
                ".xlsx": "Excel.Application",
                ".pptx": "PowerPoint.Application",
            }[extension]
            app = dispatch(program_id)
            if extension != ".pptx":
                app.Visible = False
            app.DisplayAlerts = 0
            app.AutomationSecurity = 3  # msoAutomationSecurityForceDisable

            if extension == ".docx":
                document = app.Documents.Open(
                    FileName=str(source),
                    ConfirmConversions=False,
                    ReadOnly=True,
                    AddToRecentFiles=False,
                    Visible=False,
                    OpenAndRepair=False,
                )
                document.ExportAsFixedFormat(str(temporary), 17)  # wdExportFormatPDF
            elif extension == ".xlsx":
                document = app.Workbooks.Open(
                    Filename=str(source),
                    UpdateLinks=0,
                    ReadOnly=True,
                    IgnoreReadOnlyRecommended=True,
                    AddToMru=False,
                )
                document.ExportAsFixedFormat(0, str(temporary))  # xlTypePDF
            else:
                document = app.Presentations.Open(
                    str(source), ReadOnly=True, Untitled=False, WithWindow=False
                )
                slide_count = int(document.Slides.Count)
                if slide_count < 1:
                    raise ValueError("PowerPoint PDF export needs at least one slide")
                document.ExportAsFixedFormat(
                    str(temporary),
                    2,  # ppFixedFormatTypePDF
                    1,  # ppFixedFormatIntentScreen
                    0,  # Do not frame slides
                    1,  # Horizontal handout order
                    1,  # Export slides
                    0,  # Do not print hidden slides
                    None,  # No explicit range when exporting the whole presentation
                    1,  # ppPrintAll
                    "",
                    True,  # Include document properties
                    True,  # Preserve IRM settings
                    True,  # Include document structure tags
                    True,  # Embed bitmap versions of missing fonts
                    False,  # Do not enforce PDF/A
                    getattr(pythoncom, "Missing", None),
                )

            with temporary.open("rb") as stream:
                signature = stream.read(5)
            if signature != b"%PDF-" or temporary.stat().st_size < 100:
                raise IOError("Office produced an invalid or empty PDF")
            if target.exists():
                raise FileExistsError("SHU will not overwrite an existing PDF")
            temporary.rename(target)
            return target
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            if document is not None:
                try:
                    if extension == ".xlsx":
                        document.Close(SaveChanges=False)
                    elif extension == ".docx":
                        document.Close(SaveChanges=0)
                    else:
                        document.Close()
                except Exception:
                    pass
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

    def _source_path(self, filename: str, extension: str) -> Path:
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("Source must be a plain filename inside SHU exports")
        if Path(filename).suffix.lower() != extension:
            raise ValueError(f"Source must be an {extension} file")
        source = self.paths.resolve(self.export_dir / filename, must_exist=True)
        if not source.is_file():
            raise ValueError("Office revision source must be a regular file")
        return source

    def _revision_target(self, source: Path, filename: str, extension: str) -> Path:
        normalized = self._filename(filename, extension)
        target = self.paths.resolve(self.export_dir / normalized)
        if target == source:
            raise ValueError("Office revisions must use a new output filename")
        self._refuse_overwrite(target)
        return target

    @staticmethod
    def _save_verified_output(target: Path, writer, verifier) -> Path:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=".shu-revision-", suffix=target.suffix, dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(temp_name)
        try:
            writer(temporary)
            verifier(temporary)
            if target.exists():
                raise FileExistsError("SHU will not overwrite an existing revision")
            temporary.rename(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return target

    @staticmethod
    def _require_approval(approved: bool) -> None:
        if not approved:
            raise PermissionError("Creating Office files requires explicit approval")

    @staticmethod
    def _filename(filename: str, extension: str) -> str:
        base = Path(filename).stem
        if not base or base in {".", ".."} or Path(filename).name != filename:
            raise ValueError("Only a plain filename is allowed")
        return base + extension

    @staticmethod
    def _refuse_overwrite(target: Path) -> None:
        if target.exists():
            raise FileExistsError("SHU will not overwrite an existing document")

    @staticmethod
    def _safe_cell_value(value: Any) -> Any:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Excel numeric cells must be finite")
        if value is None or isinstance(value, (int, float, bool)):
            return value
        text = str(value)[:32_000]
        if text.startswith("=") and _SAFE_FORMULA.fullmatch(text):
            return text
        if text.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + text
        return text

    @staticmethod
    def _slide_text_content(slide) -> list[tuple[str, str]]:
        return [
            (shape.name, shape.text)
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False)
        ]
