import re
import shutil
import zipfile
from pathlib import Path

import requests

from fastapi import HTTPException


class GithubHandler:
    """
    Downloads a GitHub repository as a ZIP archive
    and extracts it for RAG indexing.
    """

    # Maximum download size: 100 MB
    MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024

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

    def _parse_github_url(
        self,
        url: str
    ):
        """
        Extract owner and repo name from
        a GitHub URL.
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

        # Remove .git suffix if present
        if repo.endswith(".git"):
            repo = repo[:-4]

        return owner, repo

    def _download_zip(
        self,
        owner: str,
        repo: str
    ):
        """
        Download the repository as a ZIP archive.
        Tries 'main' branch first, then 'master'.
        """

        branches = ["main", "master"]

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

    async def clone_repo(
        self,
        repo_url: str
    ):
        """
        Download and extract a GitHub repository.
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
            owner, repo
        )

        zip_filename = f"{repo}-{branch}.zip"

        zip_path = (
            self.upload_dir / zip_filename
        )

        # Stream download with size check
        total_bytes = 0

        try:

            with open(zip_path, "wb") as f:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if chunk:

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

            zip_path.unlink(missing_ok=True)

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

        if not zipfile.is_zipfile(zip_path):

            zip_path.unlink(missing_ok=True)

            raise HTTPException(
                status_code=400,
                detail=(
                    "Downloaded file is not a "
                    "valid ZIP archive."
                )
            )

        # ========================================================
        # Extract
        # ========================================================

        project_name = repo

        project_folder = (
            self.extract_dir / project_name
        )

        if project_folder.exists():
            shutil.rmtree(project_folder)

        project_folder.mkdir(
            parents=True,
            exist_ok=True
        )

        try:

            with zipfile.ZipFile(
                zip_path, "r"
            ) as zip_ref:

                zip_ref.extractall(
                    project_folder
                )

        except Exception as e:

            shutil.rmtree(
                project_folder,
                ignore_errors=True
            )

            zip_path.unlink(missing_ok=True)

            raise HTTPException(
                status_code=500,
                detail=(
                    f"Failed to extract "
                    f"repository: {str(e)}"
                )
            )

        # ========================================================
        # GitHub ZIPs contain a top-level folder
        # like "repo-main/". Flatten if only one
        # top-level directory exists.
        # ========================================================

        top_items = list(
            project_folder.iterdir()
        )

        if (
            len(top_items) == 1
            and top_items[0].is_dir()
        ):

            inner_dir = top_items[0]

            # Move contents up one level
            for item in inner_dir.iterdir():

                target = (
                    project_folder / item.name
                )

                shutil.move(
                    str(item),
                    str(target)
                )

            # Remove empty inner directory
            shutil.rmtree(
                inner_dir,
                ignore_errors=True
            )

        # ========================================================
        # Clean up ZIP
        # ========================================================

        zip_path.unlink(missing_ok=True)

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
            f"Extracted to: {project_folder}"
        )

        return {
            "project_folder": project_folder,
            "project_name": project_name,
            "branch": branch,
            "owner": owner,
            "download_size": total_bytes
        }
