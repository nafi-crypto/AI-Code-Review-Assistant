import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None


class PdfHandler:
    """
    Extracts text/code from uploaded PDF files
    and saves it as a source file for RAG indexing.
    """

    # Maximum PDF file size: 20 MB
    MAX_PDF_SIZE = 20 * 1024 * 1024

    def __init__(
        self,
        upload_dir: Path
    ):
        self.upload_dir = upload_dir

    async def extract_code(
        self,
        file: UploadFile
    ):
        """
        Extract text from a PDF file and save
        as a source code file for analysis.
        """

        # ========================================================
        # Check PyPDF2 is available
        # ========================================================

        if PdfReader is None:

            raise HTTPException(
                status_code=500,
                detail=(
                    "PyPDF2 is not installed. "
                    "Run: pip install PyPDF2"
                )
            )

        # ========================================================
        # Validate filename
        # ========================================================

        if not file.filename:

            raise HTTPException(
                status_code=400,
                detail="Invalid file."
            )

        if not file.filename.lower().endswith(
            ".pdf"
        ):

            raise HTTPException(
                status_code=400,
                detail="Please upload a PDF file."
            )

        # ========================================================
        # Save uploaded PDF with size check
        # ========================================================

        safe_filename = Path(
            file.filename
        ).name

        pdf_path = (
            self.upload_dir / safe_filename
        )

        total_bytes = 0

        with open(pdf_path, "wb") as buffer:

            while True:

                chunk = await file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                total_bytes += len(chunk)

                if total_bytes > self.MAX_PDF_SIZE:

                    buffer.close()

                    pdf_path.unlink(
                        missing_ok=True
                    )

                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "PDF file is too large. "
                            "Maximum size is 20 MB."
                        )
                    )

                buffer.write(chunk)

        if total_bytes == 0:

            pdf_path.unlink(missing_ok=True)

            raise HTTPException(
                status_code=400,
                detail="PDF file is empty."
            )

        # ========================================================
        # Extract text from PDF
        # ========================================================

        try:

            reader = PdfReader(
                str(pdf_path)
            )

            pages = []
            page_count = len(reader.pages)

            for page in reader.pages:

                text = page.extract_text()

                if text and text.strip():
                    pages.append(
                        text.strip()
                    )

            extracted_text = (
                "\n\n".join(pages)
            )

        except Exception as e:

            pdf_path.unlink(missing_ok=True)

            print(
                "PDF extraction error:",
                repr(e)
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not read the PDF file. "
                    "It may be corrupted or "
                    "password-protected."
                )
            )

        # ========================================================
        # Validate extracted text
        # ========================================================

        if not extracted_text.strip():

            pdf_path.unlink(missing_ok=True)

            raise HTTPException(
                status_code=400,
                detail=(
                    "No readable text found in "
                    "the PDF. The file may contain "
                    "only images or scanned content."
                )
            )

        # ========================================================
        # Save extracted text as source file
        # ========================================================

        project_folder = (
            self.upload_dir / "pdf_project"
        )

        if project_folder.exists():
            shutil.rmtree(project_folder)

        project_folder.mkdir(
            parents=True,
            exist_ok=True
        )

        # Use original name with .txt extension
        base_name = Path(
            safe_filename
        ).stem

        output_filename = (
            f"{base_name}_extracted.txt"
        )

        output_path = (
            project_folder / output_filename
        )

        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(extracted_text)

        # ========================================================
        # Clean up PDF
        # ========================================================

        pdf_path.unlink(missing_ok=True)

        # ========================================================
        # Log
        # ========================================================

        print(
            f"\nPDF extracted: {safe_filename}"
        )

        print(
            f"Pages: {page_count}"
        )

        print(
            f"Extracted text: "
            f"{len(extracted_text)} characters"
        )

        print(
            f"Saved to: {output_path}"
        )

        return {
            "project_folder": project_folder,
            "file_name": output_filename,
            "page_count": page_count,
            "char_count": len(extracted_text)
        }
