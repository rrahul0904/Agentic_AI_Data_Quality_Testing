from __future__ import annotations

from email.message import EmailMessage
import io

from openpyxl import Workbook
from pptx import Presentation

from agentic_data_platform.knowledge import extract_document


def test_html_extracts_visible_text_and_excludes_script_style():
    content = b"""
    <html><head><style>.secret{display:none}</style><script>token='bad'</script></head>
    <body><h1>Incident Runbook</h1><p>Scheduler memory pressure.</p></body></html>
    """
    result = extract_document("runbook.html", content, content_type="text/html")
    assert result.source_type == "html"
    assert "Incident Runbook" in result.text
    assert "Scheduler memory pressure" in result.text
    assert "token='bad'" not in result.text
    assert "display:none" not in result.text


def test_eml_extracts_headers_body_and_attachment_metadata():
    message = EmailMessage()
    message["Subject"] = "Pipeline incident"
    message["From"] = "alerts@example.com"
    message["To"] = "data@example.com"
    message.set_content("Airflow worker was restarted after memory pressure.")
    message.add_attachment(b"binary", maintype="application", subtype="octet-stream", filename="trace.bin")
    result = extract_document("incident.eml", message.as_bytes(), content_type="message/rfc822")
    assert result.source_type == "eml"
    assert "Pipeline incident" in result.text
    assert "Airflow worker was restarted" in result.text
    assert result.metadata["attachment_count"] == 1
    assert result.metadata["attachments"] == ["trace.bin"]
    assert "binary" not in result.text


def test_pptx_extracts_slide_text_tables_and_page_markers():
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    textbox = slide.shapes.add_textbox(0, 0, 5_000_000, 1_000_000)
    textbox.text_frame.text = "Architecture Overview"
    table = slide.shapes.add_table(2, 2, 0, 1_000_000, 5_000_000, 2_000_000).table
    table.cell(0, 0).text = "Layer"
    table.cell(0, 1).text = "Service"
    table.cell(1, 0).text = "Orchestration"
    table.cell(1, 1).text = "Airflow"
    buffer = io.BytesIO()
    presentation.save(buffer)

    result = extract_document(
        "architecture.pptx",
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    assert result.source_type == "pptx"
    assert "[Page 1]" in result.text
    assert "Architecture Overview" in result.text
    assert "Orchestration | Airflow" in result.text
    assert result.metadata["slides"] == 1
    assert result.metadata["tables"] == 1


def test_xlsx_extracts_sheet_values_without_formula_execution():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Quality"
    sheet.append(["rule", "status"])
    sheet.append(["not_null", "PASS"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    result = extract_document(
        "quality.xlsx",
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert result.source_type == "xlsx"
    assert "[Sheet Quality]" in result.text
    assert "rule | status" in result.text
    assert "not_null | PASS" in result.text
    assert result.metadata["sheet_names"] == ["Quality"]
    assert result.metadata["nonempty_rows"] == 2
