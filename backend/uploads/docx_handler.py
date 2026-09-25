import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None


class DocxHandler:
    """
    Extracts text/code from uploaded document files
    (.docx, .txt) and saves for RAG indexing.
    """

    # Maximum document file size: 10 MB
    MAX_DOC_SIZE = 10 * 1024 * 1024

    # Supported document extensions
    SUPPORTED_EXTENSIONS = {
        ".docx",
        ".txt",
    }

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
        Extract text/code from a document file
        and save as a source file for analysis.
        """

        # ========================================================
        # Validate filename
        # ========================================================

        if not file.filename:

            raise HTTPException(
                status_code=400,
                detail="Invalid file."
            )

        extension = Path(
            file.filename
        ).suffix.lower()

        if (
            extension
            not in self.SUPPORTED_EXTENSIONS
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported document type. "
                    "Please upload a .docx or "
                    ".txt file."
                )
            )

        # ========================================================
        # Save uploaded file with size check
        # ========================================================

        safe_filename = Path(
            file.filename
        ).name

        doc_path = (
            self.upload_dir / safe_filename
        )

        total_bytes = 0

        with open(doc_path, "wb") as buffer:

            while True:

                chunk = await file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                total_bytes += len(chunk)

                if total_bytes > self.MAX_DOC_SIZE:

                    buffer.close()

                    doc_path.unlink(
                        missing_ok=True
                    )

                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Document is too large. "
                            "Maximum size is 10 MB."
                        )
                    )

                buffer.write(chunk)

        if total_bytes == 0:

            doc_path.unlink(missing_ok=True)

            raise HTTPException(
                status_code=400,
                detail="Document file is empty."
            )

        # ========================================================
        # Extract text based on type
        # ========================================================

        try:

            if extension == ".docx":

                extracted_text = (
                    self._extract_docx(doc_path)
                )

            else:

                extracted_text = (
                    self._extract_txt(doc_path)
                )

        except HTTPException:
            raise

        except Exception as e:

            doc_path.unlink(missing_ok=True)

            print(
                "Document extraction error:",
                repr(e)
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not read the document. "
                    "It may be corrupted."
                )
            )

        # ========================================================
        # Validate extracted text
        # ========================================================

        if not extracted_text.strip():

            doc_path.unlink(missing_ok=True)

            raise HTTPException(
                status_code=400,
                detail=(
                    "No readable text found "
                    "in the document."
                )
            )

        # ========================================================
        # Save extracted text as source file
        # ========================================================

        project_folder = (
            self.upload_dir / "doc_project"
        )

        if project_folder.exists():
            shutil.rmtree(project_folder)

        project_folder.mkdir(
            parents=True,
            exist_ok=True
        )

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
        # Clean up original document
        # ========================================================

        doc_path.unlink(missing_ok=True)

        # ========================================================
        # Log
        # ========================================================

        print(
            f"\nDocument extracted: "
            f"{safe_filename}"
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
            "char_count": len(extracted_text)
        }

    # ============================================================
    # DOCX extraction
    # ============================================================

    def _extract_docx(
        self,
        doc_path: Path
    ) -> str:
        """
        Extract text from a .docx file using
        python-docx.
        """

        if DocxDocument is None:

            raise HTTPException(
                status_code=500,
                detail=(
                    "python-docx is not installed. "
                    "Run: pip install python-docx"
                )
            )

        try:

            doc = DocxDocument(
                str(doc_path)
            )

            paragraphs = []

            for paragraph in doc.paragraphs:

                text = paragraph.text

                if text and text.strip():
                    paragraphs.append(text)

            return "\n".join(paragraphs)

        except Exception as e:

            doc_path.unlink(missing_ok=True)

            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not read the DOCX file. "
                    "It may be corrupted or "
                    "password-protected."
                )
            )

    # ============================================================
    # TXT extraction
    # ============================================================

    def _extract_txt(
        self,
        doc_path: Path
    ) -> str:
        """
        Read a plain text file directly.
        """

        try:

            return doc_path.read_text(
                encoding="utf-8",
                errors="ignore"
            )

        except Exception as e:

            doc_path.unlink(missing_ok=True)

            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not read the text file."
                )
            )
