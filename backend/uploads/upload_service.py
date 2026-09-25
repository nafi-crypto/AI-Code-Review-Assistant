from typing import List

from fastapi import UploadFile

from .zip_handler import ZipHandler
from .file_handler import FileHandler
from .paste_handler import PasteHandler
from .github_handler import GithubHandler


class UploadService:

    def __init__(
        self,
        upload_dir,
        extract_dir,
        rag_pipeline
    ):
        # ========================================================
        # ZIP Handler
        # ========================================================

        self.zip_handler = ZipHandler(
            upload_dir,
            extract_dir
        )

        # ========================================================
        # Multiple Files Handler
        # ========================================================

        self.file_handler = FileHandler(
            upload_dir
        )

        # ========================================================
        # Paste Code Handler
        # ========================================================

        self.paste_handler = PasteHandler(
            upload_dir
        )

        # ========================================================
        # GitHub Handler
        # ========================================================

        self.github_handler = GithubHandler(
            upload_dir,
            extract_dir
        )

        # ========================================================
        # Shared RAG Pipeline
        # ========================================================

        self.rag_pipeline = rag_pipeline

    # ============================================================
    # ZIP Upload
    # ============================================================

    async def process_zip_upload(
        self,
        file: UploadFile
    ):
        upload_result = await (
            self.zip_handler.extract_project(
                file
            )
        )

        metadata = (
            self.rag_pipeline
            .build_vector_database(
                str(
                    upload_result["project_folder"]
                ),
                input_type="zip",
                original_filename=file.filename
            )
        )

        # Build summary from metadata
        file_count = 0
        languages = []

        if metadata:

            file_count = metadata.get(
                "total_files",
                0
            )

            lang_data = metadata.get(
                "languages",
                {}
            )

            if isinstance(lang_data, dict):
                languages = list(
                    lang_data.keys()
                )

        return {
            "success": True,
            "message": (
                f"Project uploaded and indexed "
                f"successfully. "
                f"{file_count} source files found."
            ),
            "project_name": (
                upload_result["project_name"]
            ),
            "file_count": file_count,
            "languages": languages,
            "metadata": metadata
        }

    # ============================================================
    # Multiple Source Files Upload
    # ============================================================

    async def process_multiple_files(
        self,
        files: List[UploadFile]
    ):
        upload_result = await (
            self.file_handler.save_files(
                files
            )
        )

        is_single = len(files) == 1
        metadata = (
            self.rag_pipeline
            .build_vector_database(
                str(
                    upload_result["project_folder"]
                ),
                input_type="source_file" if is_single else "source_files",
                original_filename=files[0].filename if is_single else "source_files.zip"
            )
        )

        saved_files = upload_result.get(
            "saved_files",
            []
        )

        # Build summary from metadata
        languages = []

        if metadata:

            lang_data = metadata.get(
                "languages",
                {}
            )

            if isinstance(lang_data, dict):
                languages = list(
                    lang_data.keys()
                )

        return {
            "success": True,
            "message": (
                f"{len(saved_files)} source files "
                f"uploaded and indexed successfully."
            ),
            "project_name": "uploaded_files",
            "file_count": len(saved_files),
            "files": saved_files,
            "languages": languages,
            "input_type": "source_file" if is_single else "source_files",
            "original_filename": files[0].filename if is_single else "source_files.zip",
            "metadata": metadata
        }

    # ============================================================
    # Paste Code Upload
    # ============================================================

    def process_paste_code(
        self,
        code: str,
        filename: str
    ):
        upload_result = (
            self.paste_handler.save_code(
                code,
                filename
            )
        )

        metadata = (
            self.rag_pipeline
            .build_vector_database(
                str(
                    upload_result["project_folder"]
                ),
                input_type="pasted_code",
                original_filename=filename
            )
        )

        return {
            "success": True,
            "message": (
                "Code uploaded and indexed "
                "successfully."
            ),
            "project_name": "pasted_code",
            "file": (
                upload_result["file_name"]
            ),
            "input_type": "pasted_code",
            "original_filename": filename,
            "metadata": metadata
        }

    # ============================================================
    # GitHub Repository
    # ============================================================

    async def process_github_repo(
        self,
        repo_url: str
    ):
        upload_result = await (
            self.github_handler.clone_repo(
                repo_url
            )
        )

        metadata = (
            self.rag_pipeline
            .build_vector_database(
                str(
                    upload_result["project_folder"]
                )
            )
        )

        # Build summary from metadata
        file_count = 0
        languages = []

        if metadata:

            file_count = metadata.get(
                "total_files",
                0
            )

            lang_data = metadata.get(
                "languages",
                {}
            )

            if isinstance(lang_data, dict):
                languages = list(
                    lang_data.keys()
                )

        return {
            "success": True,
            "message": (
                f"GitHub repository "
                f"'{upload_result['project_name']}' "
                f"downloaded and indexed "
                f"successfully. "
                f"{file_count} source files found."
            ),
            "project_name": (
                upload_result["project_name"]
            ),
            "branch": upload_result["branch"],
            "file_count": file_count,
            "languages": languages,
            "metadata": metadata
        }
