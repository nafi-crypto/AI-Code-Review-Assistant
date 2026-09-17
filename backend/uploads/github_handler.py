import re
import shutil
import zipfile
from pathlib import Path

import requests

from fastapi import HTTPException


class GithubHandler:
    """
    Downloads a GitHub repository as a ZIP archive
    and safely extracts it for RAG indexing.
    """

    # Maximum GitHub ZIP download size: 100 MB
    MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024

    # Maximum number of files inside the repository ZIP
    MAX_FILE_COUNT = 500

    # Maximum total extracted size: 200 MB
    MAX_EXTRACTED_SIZE = 200 * 1024 * 1024

    # Download timeout: 60 seconds
    TIMEOUT = 60

    # GitHub URL pattern
    GITHUB_PATTERN = re.compile(
        r"(?:https?://)?(?:www\.)?github\.com/"
        r"([A-Za-z0-9_.\-]+)/"
        r"([A-Za-z0-9_.\-]+)"
        r"(?:/.*)?$"
    )

    def __init__(
        self,
        upload_dir: Path,
        extract_dir: Path
    ):
        self.upload_dir = upload_dir
        self.extract_dir = extract_dir

    # ============================================================
    # Parse GitHub URL
    # ============================================================

    def _parse_github_url(
        self,
        url: str
    ):
        """
        Extract owner and repository name
        from a GitHub URL.
        """

        url = url.strip().rstrip("/")

        match = self.GITHUB_PATTERN.match(url)

        if not match:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid GitHub URL. "
                    "Expected format: "
                    "https://github.com/owner/repo"
                )
            )

        owner = match.group(1)
        repo = match.group(2)

        if repo.endswith(".git"):
            repo = repo[:-4]

        return owner, repo

    # ============================================================
    # Download GitHub ZIP
    # ============================================================

    def _download_zip(
        self,
        owner: str,
        repo: str
    ):
        """
        Download repository ZIP.

        Tries main branch first,
        then master branch.
        """

        branches = [
            "main",
            "master"
        ]

        last_error = None

        for branch in branches:

            url = (
                f"https://github.com/"
                f"{owner}/{repo}/"
                f"archive/refs/heads/"
                f"{branch}.zip"
            )

            print(
                f"\nTrying: {url}"
            )

            try:

                response = requests.get(
                    url,
                    stream=True,
                    timeout=self.TIMEOUT,
                    allow_redirects=True
                )

                if response.status_code == 200:
                    return response, branch

                last_error = (
                    f"HTTP {response.status_code}"
                )

                print(
                    f"Branch '{branch}' "
                    f"returned {response.status_code}"
                )

            except requests.RequestException as e:

                last_error = str(e)

                print(
                    f"Branch '{branch}' "
                    f"failed: {repr(e)}"
                )

        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not download repository "
                f"'{owner}/{repo}'. "
                f"Make sure it exists and is public. "
                f"Last error: {last_error}"
            )
        )

    # ============================================================
    # Validate ZIP Members
    # ============================================================

    def _validate_zip_members(
        self,
        zip_ref: zipfile.ZipFile,
        extraction_root: Path
    ):
        """
        Validate GitHub ZIP before extraction.

        Checks:

        1. File count
        2. Total uncompressed size
        3. Path traversal
        """

        members = zip_ref.infolist()

        # --------------------------------------------------------
        # File count
        # --------------------------------------------------------

        if len(members) > self.MAX_FILE_COUNT:

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Repository contains too many "
                    f"files ({len(members)}). "
                    f"Maximum is "
                    f"{self.MAX_FILE_COUNT}."
                )
            )

        # --------------------------------------------------------
        # Extracted size
        # --------------------------------------------------------

        total_uncompressed = sum(
            member.file_size
            for member in members
        )

        if (
            total_uncompressed
            > self.MAX_EXTRACTED_SIZE
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Repository contents are too "
                    "large when extracted. "
                    "Maximum extracted size is "
                    "200 MB."
                )
            )

        # --------------------------------------------------------
        # Path traversal protection
        # --------------------------------------------------------

        for member in members:

            # Directories do not need extraction
            # path validation.
            if member.is_dir():
                continue

            target_path = (
                extraction_root /
                member.filename
            ).resolve()

            try:

                target_path.relative_to(
                    extraction_root
                )

            except ValueError:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Unsafe file path detected "
                        "inside GitHub repository."
                    )
                )

    # ============================================================
    # Clone Repository
    # ============================================================

    async def clone_repo(
        self,
        repo_url: str
    ):
        """
        Download and safely extract
        a GitHub repository.
        """

        # ========================================================
        # Parse URL
        # ========================================================

        owner, repo = self._parse_github_url(
            repo_url
        )

        print(
            f"\nGitHub download: "
            f"{owner}/{repo}"
        )

        # ========================================================
        # Download ZIP
        # ========================================================

        response, branch = self._download_zip(
            owner,
            repo
        )

        zip_filename = (
            f"{repo}-{branch}.zip"
        )

        zip_path = (
            self.upload_dir /
            zip_filename
        )

        total_bytes = 0

        try:

            with open(
                zip_path,
                "wb"
            ) as f:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if not chunk:
                        continue

                    total_bytes += len(chunk)

                    if (
                        total_bytes
                        > self.MAX_DOWNLOAD_SIZE
                    ):

                        f.close()

                        zip_path.unlink(
                            missing_ok=True
                        )

                        raise HTTPException(
                            status_code=400,
                            detail=(
                                "Repository is too "
                                "large. Maximum "
                                "download size is "
                                "100 MB."
                            )
                        )

                    f.write(chunk)

        except HTTPException:
            raise

        except Exception as e:

            zip_path.unlink(
                missing_ok=True
            )

            raise HTTPException(
                status_code=500,
                detail=(
                    f"Failed to download "
                    f"repository: {str(e)}"
                )
            )

        # ========================================================
        # Validate ZIP
        # ========================================================

        if not zipfile.is_zipfile(
            zip_path
        ):

            zip_path.unlink(
                missing_ok=True
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    "Downloaded file is not "
                    "a valid ZIP archive."
                )
            )

        # ========================================================
        # Prepare project directory
        # ========================================================

        project_name = repo

        project_folder = (
            self.extract_dir /
            project_name
        )

        if project_folder.exists():

            shutil.rmtree(
                project_folder
            )

        project_folder.mkdir(
            parents=True,
            exist_ok=True
        )

        # ========================================================
        # Validate and Extract
        # ========================================================

        try:

            with zipfile.ZipFile(
                zip_path,
                "r"
            ) as zip_ref:

                extraction_root = (
                    project_folder.resolve()
                )

                # ------------------------------------------------
                # SECURITY VALIDATION
                # ------------------------------------------------

                self._validate_zip_members(
                    zip_ref,
                    extraction_root
                )

                # ------------------------------------------------
                # Safe extraction
                # ------------------------------------------------

                for member in zip_ref.infolist():

                    if member.is_dir():
                        continue

                    target_path = (
                        project_folder /
                        member.filename
                    ).resolve()

                    try:

                        target_path.relative_to(
                            extraction_root
                        )

                    except ValueError:

                        raise HTTPException(
                            status_code=400,
                            detail=(
                                "Unsafe file path "
                                "detected inside "
                                "GitHub repository."
                            )
                        )

                    target_path.parent.mkdir(
                        parents=True,
                        exist_ok=True
                    )

                    with (
                        zip_ref.open(member, "r")
                        as source,
                        open(target_path, "wb") as target
                    ):

                        shutil.copyfileobj(
                            source,
                            target
                        )

        except HTTPException:

            shutil.rmtree(
                project_folder,
                ignore_errors=True
            )

            zip_path.unlink(
                missing_ok=True
            )

            raise

        except zipfile.BadZipFile:

            shutil.rmtree(
                project_folder,
                ignore_errors=True
            )

            zip_path.unlink(
                missing_ok=True
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    "Downloaded GitHub archive "
                    "is corrupted."
                )
            )

        except Exception as e:

            shutil.rmtree(
                project_folder,
                ignore_errors=True
            )

            zip_path.unlink(
                missing_ok=True
            )

            raise HTTPException(
                status_code=500,
                detail=(
                    f"Failed to extract "
                    f"repository: {str(e)}"
                )
            )

        # ========================================================
        # Flatten GitHub top-level directory
        # ========================================================

        top_items = list(
            project_folder.iterdir()
        )

        if (
            len(top_items) == 1
            and top_items[0].is_dir()
        ):

            inner_dir = top_items[0]

            for item in inner_dir.iterdir():

                target = (
                    project_folder /
                    item.name
                )

                # Avoid accidental overwrite
                # if a collision exists.
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()

                shutil.move(
                    str(item),
                    str(target)
                )

            shutil.rmtree(
                inner_dir,
                ignore_errors=True
            )

        # ========================================================
        # Clean up ZIP
        # ========================================================

        zip_path.unlink(
            missing_ok=True
        )

        # ========================================================
        # Log
        # ========================================================

        print(
            f"\nGitHub repo extracted: "
            f"{owner}/{repo} ({branch})"
        )

        print(
            f"Downloaded: "
            f"{total_bytes / 1024 / 1024:.1f} MB"
        )

        print(
            f"Extracted to: "
            f"{project_folder}"
        )

        return {
            "project_folder": project_folder,
            "project_name": project_name,
            "branch": branch,
            "owner": owner,
            "download_size": total_bytes
        }