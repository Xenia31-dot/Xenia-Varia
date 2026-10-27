from rfp.ingestion import chunk_text, document_id, extract_sections, ingest_file

from .helpers import make_docx, make_pdf, make_xlsx


def test_pdf_pages_keep_page_numbers():
    data = make_pdf(["Encryption uses AES-256.", "Support is available 24/7."])
    sections = extract_sections("product.pdf", data)
    assert [s.location for s in sections] == ["page 1", "page 2"]
    assert "AES-256" in sections[0].text


def test_docx_groups_text_under_headings_and_reads_tables():
    data = make_docx(
        [("Heading 1", "Security"), ("Normal", "We use SSO via SAML 2.0.")],
        table=[["Feature", "Status"], ["MFA", "Available"]],
    )
    sections = extract_sections("security.docx", data)
    assert sections[0].location == "section 'Security'"
    assert "SAML 2.0" in sections[0].text
    assert "MFA | Available" in sections[0].text


def test_xlsx_rows_include_headers_and_sheet_location():
    data = make_xlsx({"Pricing": [["Plan", "Price"], ["Pro", "$20"], ["Team", "$50"]]})
    sections = extract_sections("pricing.xlsx", data)
    assert sections[0].location == "sheet 'Pricing' rows 2-3"
    assert "Plan: Pro; Price: $20" in sections[0].text


def test_chunking_respects_size_and_overlaps():
    text = "\n".join(f"Sentence number {i} is about feature {i}." for i in range(200))
    chunks = chunk_text(text, size=300, overlap=60)
    assert len(chunks) > 5
    assert all(len(c) <= 360 for c in chunks)
    # overlap: the end of one chunk reappears at the start of the next
    assert chunks[0].split()[-1] in chunks[1]


def test_ingest_file_adds_metadata():
    chunks = ingest_file("Product Sheet.pdf", make_pdf(["Hello world"]), upload_date="2026-01-01")
    meta = chunks[0].metadata
    assert meta["source"] == "Product Sheet.pdf"
    assert meta["location"] == "page 1"
    assert meta["upload_date"] == "2026-01-01"
    assert meta["doc_id"] == document_id("product sheet.pdf")


def test_unsupported_type_raises():
    import pytest

    with pytest.raises(ValueError):
        extract_sections("image.png", b"...")
