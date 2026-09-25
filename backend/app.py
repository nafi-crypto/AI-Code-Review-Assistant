# ============================================================
# AI CODE REVIEW ASSISTANT
# backend/app.py
# ============================================================

import os
import json

from pathlib import Path
from typing import List, Any, Dict, Optional
import uuid

from dotenv import load_dotenv

import io
import zipfile

from fastapi import (
    FastAPI,
    HTTPException,
    UploadFile,
    File,
    Request
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from fastapi.middleware.cors import CORSMiddleware

from pydantic import (
    BaseModel,
    ValidationError
)

from groq import Groq
import httpx

from rag.pipeline import RAGPipeline

from uploads.upload_service import UploadService

from services.review_service import ReviewService

from models.review_models import (
    ReviewRequest,
    StructuredReview,
    FileAnalyzed,
    DetectedIssue
)

from db.database import init_db
from db import crud
from services.security_service import (
    validate_uploaded_file,
    validate_file_extension,
    sanitize_filename
)



# Load .env from backend folder and current working directory
backend_env = Path(__file__).resolve().parent / ".env"
if backend_env.exists():
    load_dotenv(dotenv_path=backend_env)
load_dotenv()

API_KEY = os.getenv("GROQ_API_KEY", "")

if not API_KEY:
    print("WARNING: GROQ_API_KEY not found in environment or .env file.")


# ============================================================
# GROQ CLIENT
# ============================================================

try:
    client = Groq(
        api_key=API_KEY or "gsk_placeholder",
        http_client=httpx.Client(verify=False)
    )
except Exception:
    client = Groq(
        api_key=API_KEY or "gsk_placeholder"
    )


# ============================================================
# RAG PIPELINE
# ============================================================

rag_pipeline = RAGPipeline()


# ============================================================
# DIRECTORIES
# ============================================================

UPLOAD_DIR = Path("uploads")

UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)


EXTRACT_DIR = Path("extracted")

EXTRACT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# UPLOAD SERVICE
# ============================================================

upload_service = UploadService(
    upload_dir=UPLOAD_DIR,
    extract_dir=EXTRACT_DIR,
    rag_pipeline=rag_pipeline
)


# ============================================================
# REVIEW SERVICE
# ============================================================

review_service = ReviewService(
    rag_pipeline=rag_pipeline,
    groq_client=client
)


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="AI Code Review Assistant",
    version="1.4.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ============================================================
# GROQ MODEL CONFIGURATION
# ============================================================

AVAILABLE_GROQ_MODELS = [
    {
        "id": "qwen/qwen3.8-27b",
        "name": "Qwen 3 27B",
        "description": "Ultra-fast LPU inference, high rate limits, specialized code analysis",
        "recommended": True,
        "max_tokens": 2048
    },
    {
        "id": "openai/gpt-oss-20b",
        "name": "GPT-OSS 20B",
        "description": "Deep reasoning model with balanced analysis",
        "recommended": False,
        "max_tokens": 4096
    },
    {
        "id": "groq/compound",
        "name": "Groq Compound",
        "description": "High-throughput multi-agent architecture",
        "recommended": False,
        "max_tokens": 4096
    },
    {
        "id": "openai/gpt-oss-120b",
        "name": "GPT-OSS 120B",
        "description": "Massive 120B parameter reasoning model",
        "recommended": False,
        "max_tokens": 4096
    },
    {
        "id": "groq/compound-mini",
        "name": "Groq Compound Mini",
        "description": "Ultra-lightweight fast response model",
        "recommended": False,
        "max_tokens": 4096
    }
]

DEFAULT_GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")


@app.get("/api/models")
async def get_available_models():
    return {
        "success": True,
        "current_default": DEFAULT_GROQ_MODEL,
        "models": AVAILABLE_GROQ_MODELS
    }


# ============================================================
# PASTE CODE REQUEST
# ============================================================

class PasteCodeRequest(BaseModel):

    filename: str

    code: str


# ============================================================
# GITHUB REQUEST
# ============================================================

class GithubRequest(BaseModel):

    repo_url: str


# ============================================================
# DOWNLOAD CODE REQUEST
# ============================================================

class DownloadCodeRequest(BaseModel):

    filename: str

    code: str


# ============================================================
# GROQ STRICT JSON SCHEMA
# ============================================================

def build_groq_schema(
    model: Any
) -> dict:
    """
    Convert Pydantic schema into Groq-compatible
    strict JSON schema.
    """

    raw_schema = model.model_json_schema()

    definitions = raw_schema.get(
        "$defs",
        {}
    )

    # ========================================================
    # RESOLVE REFERENCES
    # ========================================================

    def resolve_reference(
        value: Any
    ) -> Any:

        if isinstance(value, dict):

            if "$ref" in value:

                reference = value["$ref"]

                prefix = "#/$defs/"

                if reference.startswith(prefix):

                    name = reference[
                        len(prefix):
                    ]

                    if name in definitions:

                        return resolve_reference(
                            definitions[name]
                        )

                return {}

            return {
                key: resolve_reference(item)
                for key, item in value.items()
                if key != "$defs"
            }

        if isinstance(value, list):

            return [
                resolve_reference(item)
                for item in value
            ]

        return value

    schema = resolve_reference(
        raw_schema
    )

    # ========================================================
    # SANITIZE
    # ========================================================

    allowed_keys = {
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "anyOf",
        "oneOf",
        "description"
    }

    def sanitize(
        value: Any
    ) -> Any:

        if isinstance(value, list):

            return [
                sanitize(item)
                for item in value
            ]

        if not isinstance(
            value,
            dict
        ):

            return value

        result = {}

        # ----------------------------------------------------
        # OBJECT
        # ----------------------------------------------------

        if value.get("type") == "object":

            result["type"] = "object"

            properties = value.get(
                "properties",
                {}
            )

            # Filter out backend-computed properties such as detected_issues,
            # and redundant duplicate fields on finding objects that cause strict schema validation failures.
            filtered_properties = {}
            for k, v in properties.items():
                if k == "detected_issues":
                    continue
                if k in ("explanation", "suggested_solution", "before_code", "after_code", "reason_for_correction"):
                    continue
                if k == "corrected_code" and v.get("type") != "array" and not (
                    isinstance(v.get("anyOf"), list)
                    and any(item.get("type") == "array" for item in v.get("anyOf", []))
                ):
                    continue
                filtered_properties[k] = v

            result["properties"] = {
                key: sanitize(
                    property_schema
                )
                for key, property_schema
                in filtered_properties.items()
            }

            result["required"] = list(
                filtered_properties.keys()
            )

            result[
                "additionalProperties"
            ] = False

            if "description" in value:

                result["description"] = (
                    value["description"]
                )

            return result

        # ----------------------------------------------------
        # ARRAY
        # ----------------------------------------------------

        if value.get("type") == "array":

            result["type"] = "array"

            if "items" in value:

                result["items"] = sanitize(
                    value["items"]
                )

            if "description" in value:

                result["description"] = (
                    value["description"]
                )

            return result

        # ----------------------------------------------------
        # UNION
        # ----------------------------------------------------

        if "anyOf" in value:

            result["anyOf"] = [
                sanitize(item)
                for item in value["anyOf"]
            ]

            if "description" in value:

                result["description"] = (
                    value["description"]
                )

            return result

        # ----------------------------------------------------
        # ENUM / PRIMITIVE
        # ----------------------------------------------------

        for key in allowed_keys:

            if key in value:

                result[key] = sanitize(
                    value[key]
                )

        return result

    return sanitize(
        schema
    )


# ============================================================
# BUILD SCHEMA
# ============================================================

GROQ_REVIEW_SCHEMA = build_groq_schema(
    StructuredReview
)

print("\n========== GROQ SCHEMA DEBUG ==========")
print(
    json.dumps(
        GROQ_REVIEW_SCHEMA,
        indent=2,
        ensure_ascii=False
    )
)
print("=======================================\n")

# ============================================================
# CLEAN JSON
# ============================================================

def clean_json_response(
    content: str
) -> str:

    if not content:

        return ""

    content = content.strip()

    if content.startswith(
        "```json"
    ):

        content = content[
            len("```json"):
        ]

    elif content.startswith(
        "```"
    ):

        content = content[
            len("```"):
        ]

    if content.endswith(
        "```"
    ):

        content = content[
            :-len("```")
        ]

    return content.strip()


# ============================================================
# ROBUST PRE-NORMALIZATION FOR LLM JSON OUTPUT
# ============================================================

def robust_pre_normalize(data: Any) -> dict:
    """
    Normalizes raw LLM-generated JSON before Pydantic validation to ensure
    it never fails due to minor formatting mismatches (e.g., security/performance
    returned as list instead of object, string lists for observations, float confidence, etc.).
    """
    if not isinstance(data, dict):
        return {}

    # Required top-level fallback defaults
    data.setdefault("project", {"name": "Analyzed Code", "languages": ["Source"], "total_files": 1, "total_lines": 1})
    data.setdefault("question", "Code review")
    data.setdefault("user_requirements", [])
    data.setdefault("review_types", ["full_review"])
    data.setdefault("answer_summary", "The code review has completed.")
    data.setdefault("files_analyzed", [])
    data.setdefault("key_methods", [])
    data.setdefault("key_classes", [])
    data.setdefault("libraries", [])
    data.setdefault("bugs", [])
    data.setdefault("errors", [])
    data.setdefault("performance", None)
    data.setdefault("security", None)
    data.setdefault("code_quality", None)
    data.setdefault("corrected_code", [])
    data.setdefault("expected_output", None)
    data.setdefault("score", None)
    data.setdefault("confidence", 85)
    data.setdefault("final_verdict", "Analysis complete.")

    # Ensure list types for array fields
    for list_key in ["user_requirements", "review_types", "key_methods", "key_classes", "libraries"]:
        val = data.get(list_key)
        if not isinstance(val, list):
            data[list_key] = [str(val)] if val is not None else []
        else:
            data[list_key] = [str(x) for x in val if x is not None]

    # Confidence normalization (handle float like 0.9 -> 90)
    conf = data.get("confidence")
    if isinstance(conf, float):
        data["confidence"] = int(conf * 100) if 0 < conf <= 1 else int(conf)
    elif isinstance(conf, int):
        data["confidence"] = max(0, min(100, conf))

    # Corrected code normalization (handle string -> list of dicts)
    if isinstance(data.get("corrected_code"), str):
        data["corrected_code"] = [{"file_name": "refactored_code", "code": data["corrected_code"]}]
    elif isinstance(data.get("corrected_code"), list):
        norm_cc = []
        for item in data["corrected_code"]:
            if isinstance(item, str):
                norm_cc.append({"file_name": "refactored_code", "code": item})
            elif isinstance(item, dict):
                norm_cc.append({
                    "file_name": str(item.get("file_name") or "refactored_code"),
                    "code": str(item.get("code") or "")
                })
        data["corrected_code"] = norm_cc

    # Pre-normalize security (LLM often returns a list of security issues)
    sec = data.get("security")
    if isinstance(sec, list):
        data["security"] = {"issues_found": len(sec), "issues": sec}
    elif isinstance(sec, dict):
        if "issues" not in sec or not isinstance(sec["issues"], list):
            sec["issues"] = []
        sec["issues_found"] = len(sec["issues"])
    elif sec is not None:
        data["security"] = None

    # Pre-normalize performance (LLM often returns a list of performance issues)
    perf = data.get("performance")
    if isinstance(perf, list):
        data["performance"] = {"time_complexity": None, "space_complexity": None, "issues": perf}
    elif isinstance(perf, dict):
        if "issues" not in perf or not isinstance(perf["issues"], list):
            perf["issues"] = []
    elif perf is not None:
        data["performance"] = None

    # Pre-normalize files_analyzed
    if not isinstance(data.get("files_analyzed"), list):
        data["files_analyzed"] = []
    else:
        norm_fa = []
        for fa in data["files_analyzed"]:
            if isinstance(fa, str):
                norm_fa.append({"file_name": fa, "path": fa, "language": "Source"})
            elif isinstance(fa, dict):
                norm_fa.append({
                    "file_name": str(fa.get("file_name") or "main.py"),
                    "path": str(fa.get("path") or "main.py"),
                    "language": str(fa.get("language") or "Source")
                })
        data["files_analyzed"] = norm_fa

    # Pre-normalize code_quality
    cq = data.get("code_quality")
    if isinstance(cq, list):
        data["code_quality"] = {"observations": [], "suggestions": cq}
        cq = data["code_quality"]

    if isinstance(cq, dict):
        cq.setdefault("observations", [])
        cq.setdefault("suggestions", [])
        for key in ["observations", "suggestions"]:
            items = cq.get(key, [])
            if isinstance(items, list):
                new_items = []
                for it in items:
                    if isinstance(it, str):
                        new_items.append({"title": it[:60], "description": it, "severity": "low"})
                    elif isinstance(it, dict):
                        if isinstance(it.get("line_range"), list):
                            it["line_range"] = "-".join(map(str, it["line_range"]))
                        it.setdefault("title", "Code Quality Finding")
                        it.setdefault("description", it.get("explanation") or it.get("impact") or "Quality improvement suggestion")
                        it.setdefault("severity", "low")
                        new_items.append(it)
                cq[key] = new_items

    # Sanitize finding items
    def sanitize_finding_list(finding_list, default_cat):
        if not isinstance(finding_list, list):
            return []
        sanitized = []
        for f in finding_list:
            if isinstance(f, str):
                f = {"title": f[:60], "description": f}
            if isinstance(f, dict):
                if isinstance(f.get("line_range"), list):
                    f["line_range"] = "-".join(map(str, f["line_range"]))
                f.setdefault("title", f"Detected {default_cat.capitalize()} Issue")
                f.setdefault("description", f.get("explanation") or f.get("impact") or f["title"])
                f.setdefault("file", "main.py")
                f.setdefault("evidence", f.get("before_code") or "")
                f.setdefault("impact", "Impacts code quality, reliability, or security.")
                f.setdefault("fix", f.get("suggested_solution") or f.get("suggestion") or "Refactor code according to best practices.")
                f.setdefault("severity", "high" if default_cat in ["bug", "error"] else "medium")
                if f["severity"] not in ["critical", "high", "medium", "low"]:
                    f["severity"] = "high" if default_cat in ["bug", "error"] else "medium"
                if default_cat == "bug":
                    f.setdefault("type", "confirmed")
                    f.setdefault("confidence", 85)
                elif default_cat == "error":
                    f.setdefault("type", "runtime_error")
                    f.setdefault("confidence", 85)
                sanitized.append(f)
        return sanitized

    data["bugs"] = sanitize_finding_list(data.get("bugs", []), "bug")
    data["errors"] = sanitize_finding_list(data.get("errors", []), "error")
    if data.get("security") and isinstance(data["security"].get("issues"), list):
        data["security"]["issues"] = sanitize_finding_list(data["security"]["issues"], "security")
        data["security"]["issues_found"] = len(data["security"]["issues"])
    if data.get("performance") and isinstance(data["performance"].get("issues"), list):
        data["performance"]["issues"] = sanitize_finding_list(data["performance"]["issues"], "performance")

    return data


# ============================================================
# BUILD TRUSTED FILE LIST
# ============================================================

def build_trusted_files_analyzed(
    retrieved_chunks: List[Dict]
) -> List[FileAnalyzed]:
    """
    IMPORTANT:

    files_analyzed must NEVER come from the LLM.

    It is derived exclusively from the chunks that were
    actually retrieved for THIS review.

    This prevents stale filenames from previous projects
    appearing in the final response.
    """

    files = []

    seen = set()

    for chunk in retrieved_chunks:

        file_name = (
            chunk.get("name")
            or chunk.get("file_name")
            or "Unknown"
        )

        path = (
            chunk.get("relative_path")
            or chunk.get("path")
            or file_name
        )

        language = (
            chunk.get("language")
            or "Unknown"
        )

        identity = (
            str(path).lower()
        )

        if identity in seen:

            continue

        seen.add(
            identity
        )

        files.append(
            FileAnalyzed(
                file_name=str(
                    file_name
                ),

                path=str(
                    path
                ),

                language=str(
                    language
                )
            )
        )

    return files


# ============================================================
# BUILD TRUSTED PROJECT INFO
# ============================================================

def build_trusted_project_info(
    retrieved_chunks: List[Dict],
    existing_project: Any
):
    """
    Project information should preferably come from the
    current indexed project metadata.

    The LLM should not be trusted to invent project statistics.
    """

    metadata = {}

    if isinstance(
        existing_project,
        dict
    ):

        metadata = existing_project

    # --------------------------------------------------------
    # Files represented by CURRENT retrieval
    # --------------------------------------------------------

    trusted_files = (
        build_trusted_files_analyzed(
            retrieved_chunks
        )
    )

    # --------------------------------------------------------
    # Language fallback
    # --------------------------------------------------------

    languages = []

    for file in trusted_files:

        if (
            file.language
            and file.language != "Unknown"
            and file.language not in languages
        ):

            languages.append(
                file.language
            )

    metadata_languages = metadata.get(
        "languages",
        []
    )

    if isinstance(
        metadata_languages,
        dict
    ):

        metadata_languages = list(
            metadata_languages.keys()
        )

    if not languages:

        languages = (
            metadata_languages
            if isinstance(
                metadata_languages,
                list
            )
            else []
        )

    # --------------------------------------------------------
    # Project name
    # --------------------------------------------------------

    project_name = (
        metadata.get(
            "project_name"
        )
        or metadata.get(
            "name"
        )
        or "Current Project"
    )

    # --------------------------------------------------------
    # Total lines
    # --------------------------------------------------------

    total_lines = metadata.get(
        "total_lines",
        0
    )

    try:

        total_lines = int(
            total_lines
        )

    except (
        TypeError,
        ValueError
    ):

        total_lines = 0

    return {
        "name": project_name,
        "languages": languages,
        "total_files": len(
            trusted_files
        ),
        "total_lines": total_lines
    }


# ============================================================
# VALIDATE FINDINGS
# ============================================================

def validate_findings(
    review: StructuredReview
) -> StructuredReview:

    # ========================================================
    # BUGS
    # ========================================================

    verified_bugs = []

    for bug in review.bugs:

        if not bug.evidence.strip():

            print(
                "Rejected bug without evidence:",
                bug.title
            )

            continue

        if not bug.file.strip():

            print(
                "Rejected bug without file:",
                bug.title
            )

            continue

        verified_bugs.append(
            bug
        )

    review.bugs = verified_bugs

    # ========================================================
    # ERRORS
    # ========================================================

    verified_errors = []

    for error in review.errors:

        if not error.evidence.strip():

            print(
                "Rejected error without evidence:",
                error.title
            )

            continue

        if not error.file.strip():

            print(
                "Rejected error without file:",
                error.title
            )

            continue

        verified_errors.append(
            error
        )

    review.errors = verified_errors

    # ========================================================
    # SECURITY COUNT
    # ========================================================

    if review.security:

        review.security.issues_found = len(
            review.security.issues
        )

    return review


# ============================================================
# NORMALIZE REVIEW
# ============================================================

def normalize_review(
    review: StructuredReview,
    question: str
) -> StructuredReview:

    # ========================================================
    # SUMMARY
    # ========================================================

    if not review.answer_summary.strip():

        bug_count = len(
            review.bugs
        )

        error_count = len(
            review.errors
        )

        security_count = 0

        if review.security:

            security_count = len(
                review.security.issues
            )

        performance_count = 0

        if review.performance:

            performance_count = len(
                review.performance.issues
            )

        quality_count = 0

        if review.code_quality:

            quality_count = (
                len(
                    review.code_quality.observations
                )
                +
                len(
                    review.code_quality.suggestions
                )
            )

        findings = []

        if bug_count:

            findings.append(
                f"{bug_count} bug"
                +
                (
                    "s"
                    if bug_count != 1
                    else ""
                )
            )

        if error_count:

            findings.append(
                f"{error_count} error"
                +
                (
                    "s"
                    if error_count != 1
                    else ""
                )
            )

        if security_count:

            findings.append(
                f"{security_count} security issue"
                +
                (
                    "s"
                    if security_count != 1
                    else ""
                )
            )

        if performance_count:

            findings.append(
                f"{performance_count} performance concern"
                +
                (
                    "s"
                    if performance_count != 1
                    else ""
                )
            )

        if quality_count:

            findings.append(
                f"{quality_count} code-quality finding"
                +
                (
                    "s"
                    if quality_count != 1
                    else ""
                )
            )

        if findings:

            review.answer_summary = (
                "The review identified "
                +
                ", ".join(
                    findings
                )
                +
                ". See the detailed findings below."
            )

        else:

            review.answer_summary = (
                "The project was reviewed successfully. "
                "No supported issues were identified "
                "for the requested analysis."
            )

    # ========================================================
    # FINAL VERDICT
    # ========================================================

    if not review.final_verdict.strip():

        security_count = 0

        if review.security:

            security_count = len(
                review.security.issues
            )

        performance_count = 0

        if review.performance:

            performance_count = len(
                review.performance.issues
            )

        quality_count = 0

        if review.code_quality:

            quality_count = (
                len(
                    review.code_quality.observations
                )
                +
                len(
                    review.code_quality.suggestions
                )
            )

        total_findings = (
            len(review.bugs)
            +
            len(review.errors)
            +
            security_count
            +
            performance_count
            +
            quality_count
        )

        if total_findings == 0:

            review.final_verdict = (
                "No supported issues were identified "
                "in the analyzed project."
            )

        else:

            review.final_verdict = (
                f"The review identified "
                f"{total_findings} supported finding"
                +
                (
                    "s"
                    if total_findings != 1
                    else ""
                )
                +
                " across the requested analysis areas. "
                "The highest-severity findings should be "
                "addressed before production use."
            )

    # ========================================================
    # SECURITY COUNT
    # ========================================================

    if review.security:

        review.security.issues_found = len(
            review.security.issues
        )

    # ========================================================
    # METHODS
    # ========================================================

    review.key_methods = list(
        dict.fromkeys(
            method.strip()
            for method in review.key_methods
            if isinstance(
                method,
                str
            )
            and method.strip()
        )
    )

    # ========================================================
    # CLASSES
    # ========================================================

    review.key_classes = list(
        dict.fromkeys(
            item.strip()
            for item in review.key_classes
            if isinstance(
                item,
                str
            )
            and item.strip()
        )
    )

    # ========================================================
    # LIBRARIES
    # ========================================================

    review.libraries = list(
        dict.fromkeys(
            item.strip()
            for item in review.libraries
            if isinstance(
                item,
                str
            )
            and item.strip()
        )
    )

    # ========================================================
    # PERFORMANCE
    # ========================================================

    if review.performance:

        performance_text = ""

        for issue in (
            review.performance.issues
        ):

            performance_text += (
                " "
                + (
                    issue.title
                    or ""
                )
            )

            performance_text += (
                " "
                + (
                    issue.description
                    or ""
                )
            )

            performance_text += (
                " "
                + (
                    issue.evidence
                    or ""
                )
            )

        performance_text = (
            performance_text.lower()
        )

        quadratic_indicators = [
            "o(n^2)",
            "o(n²)",
            "quadratic",
            "nested loop",
            "nested loops",
            "quadratic time"
        ]

        if any(
            indicator
            in performance_text
            for indicator
            in quadratic_indicators
        ):

            review.performance.time_complexity = (
                "O(n²)"
            )

    # ========================================================
    # CONFIDENCE
    # ========================================================

    confidences = []

    for bug in review.bugs:

        if bug.confidence is not None and bug.confidence > 0:

            confidences.append(
                bug.confidence
            )

    for error in review.errors:

        if error.confidence is not None and error.confidence > 0:

            confidences.append(
                error.confidence
            )

    if review.performance:

        for issue in (
            review.performance.issues
        ):

            if issue.confidence is not None and issue.confidence > 0:

                confidences.append(
                    issue.confidence
                )

    if review.security:

        for issue in (
            review.security.issues
        ):

            if getattr(issue, "confidence", None) is not None and issue.confidence > 0:

                confidences.append(
                    issue.confidence
                )

    # --------------------------------------------------------
    # Use finding confidence when findings contain confidence
    # --------------------------------------------------------

    if confidences:

        review.confidence = round(
            sum(
                confidences
            )
            /
            len(
                confidences
            )
        )

    # --------------------------------------------------------
    # Findings exist but individual confidence was not supplied
    # --------------------------------------------------------

    elif (
        review.bugs
        or review.errors
        or (
            review.security
            and review.security.issues
        )
        or (
            review.performance
            and review.performance.issues
        )
        or (
            review.code_quality
            and (
                review.code_quality.observations
                or
                review.code_quality.suggestions
            )
        )
    ):

        review.confidence = 80

    # --------------------------------------------------------
    # Clean review
    # --------------------------------------------------------
    # No findings does NOT mean zero confidence.
    # It means the model found no issues in the analyzed source.
    # --------------------------------------------------------

    else:

        review.confidence = 95
    # ========================================================
    # 8-POINT SOLUTION & CODE CORRECTION NORMALIZATION
    # ========================================================
    detected_list = []

    def _normalize_item(item, category: str, default_sev: str):
        # 1. Problem Identification
        current_title = getattr(item, "title", "") or ""
        if not current_title.strip():
            desc_text = getattr(item, "description", "") or ""
            item.title = desc_text.split(".")[0] if desc_text else f"Detected {category} issue"

        # 2. File & Line
        current_file = getattr(item, "file", None)
        if not current_file or not str(current_file).strip():
            item.file = "main.py"

        # 3. Explanation
        exp = getattr(item, "explanation", None) or getattr(item, "description", None) or ""
        desc = getattr(item, "description", None) or exp or ""
        item.explanation = exp or desc
        item.description = desc or exp

        # 4. Severity
        sev = getattr(item, "severity", None)
        if sev not in ["critical", "high", "medium", "low"]:
            item.severity = default_sev

        # 5. Suggested Solution
        sol = (
            getattr(item, "suggested_solution", None)
            or getattr(item, "fix", None)
            or getattr(item, "suggestion", None)
            or "Apply recommended security and code quality practices to resolve this issue."
        )
        item.suggested_solution = sol
        if hasattr(item, "fix"):
            item.fix = getattr(item, "fix", None) or sol
        if hasattr(item, "suggestion"):
            item.suggestion = getattr(item, "suggestion", None) or sol

        # 6 & 7. Before and After Code
        before = getattr(item, "before_code", None) or getattr(item, "evidence", None) or ""
        after = getattr(item, "after_code", None) or getattr(item, "corrected_code", None) or ""

        item.before_code = before
        if hasattr(item, "evidence"):
            item.evidence = getattr(item, "evidence", None) or before
        item.after_code = after
        item.corrected_code = after or getattr(item, "corrected_code", None)

        # 8. Reason for Correction
        reason = getattr(item, "reason_for_correction", None)
        if not reason or not str(reason).strip():
            imp = getattr(item, "impact", None)
            if imp and str(imp).strip():
                item.reason_for_correction = f"Prevents {str(imp).lower()} and ensures adherence to production quality standards."
            else:
                item.reason_for_correction = f"Improves reliability, security, and maintainability by resolving the {item.severity}-severity {category} flaw."

        return DetectedIssue(
            title=item.title,
            category=category,
            file=item.file,
            line=getattr(item, "line", None),
            line_range=getattr(item, "line_range", None),
            description=item.description,
            explanation=item.explanation,
            severity=item.severity,
            suggested_solution=item.suggested_solution,
            before_code=item.before_code,
            after_code=item.after_code,
            corrected_code=item.corrected_code,
            reason_for_correction=item.reason_for_correction,
            impact=getattr(item, "impact", None),
            confidence=getattr(item, "confidence", None)
        )

    for b in review.bugs:
        detected_list.append(_normalize_item(b, "bug", "high"))

    for e in review.errors:
        detected_list.append(_normalize_item(e, "error", "high"))

    if review.security:
        for s in review.security.issues:
            detected_list.append(_normalize_item(s, "security", "medium"))

    if review.performance:
        for p in review.performance.issues:
            detected_list.append(_normalize_item(p, "performance", "medium"))

    if review.code_quality:
        for o in review.code_quality.observations:
            detected_list.append(_normalize_item(o, "code_quality", "low"))
        for sq in review.code_quality.suggestions:
            detected_list.append(_normalize_item(sq, "code_quality", "low"))

    review.detected_issues = detected_list

    # ========================================================
    # QUESTION
    # ========================================================

    review.question = question

    return review


# ============================================================
# FRONTEND STATIC ASSETS & HOME
# ============================================================

FRONTEND_BUILD_DIR = Path(__file__).resolve().parent.parent / "frontend" / "build"
if not FRONTEND_BUILD_DIR.exists():
    FRONTEND_BUILD_DIR = Path(__file__).resolve().parent / "static"

if FRONTEND_BUILD_DIR.exists() and (FRONTEND_BUILD_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_BUILD_DIR / "static")), name="static")


# Initialize SQLite database on load
try:
    init_db()
except Exception as _e:
    print(f"[DB] Database initialization notice: {repr(_e)}")


# ============================================================
# USER AUTHENTICATION / IDENTITY EXTRACTION HELPER
# ============================================================

def get_request_user(request: Request) -> Dict[str, str]:
    """
    Extracts authenticated user identity from incoming request headers.
    Supports Clerk user headers X-User-Id, X-User-Email, X-User-Name,
    or Authorization Bearer token.
    """
    user_id = request.headers.get("X-User-Id", "").strip()
    user_email = request.headers.get("X-User-Email", "").strip()
    user_name = request.headers.get("X-User-Name", "").strip()

    # Support Authorization header if X-User-Id was not explicitly set
    if not user_id:
        auth_header = request.headers.get("Authorization", "").strip()
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if token.startswith("user_"):
                user_id = token

    return {
        "id": user_id,
        "email": user_email,
        "name": user_name
    }


# ============================================================
# API MODELS FOR USER, THEME, REVIEWS
# ============================================================

class UserSyncRequest(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = ""
    image_url: Optional[str] = ""


class ThemeRequest(BaseModel):
    theme: str


# ============================================================
# USER & AUTH DATABASE ENDPOINTS
# ============================================================

@app.post("/api/users/sync")
def sync_user(data: UserSyncRequest):
    """
    Upserts user record into SQLite when a user signs in via Clerk.
    """
    try:
        user = crud.upsert_user(
            user_id=data.id,
            email=data.email,
            full_name=data.full_name,
            image_url=data.image_url
        )
        return {"success": True, "user": user}
    except Exception as e:
        print("User Sync Error:", repr(e))
        raise HTTPException(status_code=500, detail="Failed to sync user data")


@app.get("/api/users/me")
def get_current_user_profile(request: Request):
    """
    Returns profile information for the authenticated user from SQLite.
    """
    u = get_request_user(request)
    if not u["id"]:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = crud.get_user(u["id"])
    if not user:
        user = crud.upsert_user(u["id"], u["email"] or f"{u['id']}@user.local", u["name"])
    return {"success": True, "user": user}


# ============================================================
# THEME PREFERENCE ENDPOINTS
# ============================================================

@app.get("/api/user/theme")
def get_theme(request: Request):
    """
    Retrieves the user's saved theme preference from SQLite (default 'dark').
    """
    u = get_request_user(request)
    if not u["id"]:
        return {"theme": "dark"}
    theme = crud.get_user_theme(u["id"])
    return {"theme": theme}


@app.put("/api/user/theme")
def update_theme(data: ThemeRequest, request: Request):
    """
    Persists user's selected theme preference in SQLite.
    """
    u = get_request_user(request)
    if not u["id"]:
        return {"success": True, "theme": data.theme, "note": "Guest theme"}
    crud.update_user_theme(u["id"], data.theme)
    return {"success": True, "theme": data.theme}


# ============================================================
# REVIEW HISTORY DATABASE ENDPOINTS
# ============================================================

@app.get("/api/reviews")
def get_user_reviews_endpoint(request: Request):
    """
    Returns list of code reviews belonging exclusively to the authenticated user.
    """
    u = get_request_user(request)
    if not u["id"]:
        raise HTTPException(status_code=401, detail="Authentication required to view review history")
    reviews = crud.get_user_reviews(u["id"])
    return {"success": True, "reviews": reviews}


@app.get("/api/reviews/{review_id}")
def get_single_review_endpoint(review_id: str, request: Request):
    """
    Returns full details and AI results of a specific review if owned by user.
    """
    u = get_request_user(request)
    if not u["id"]:
        raise HTTPException(status_code=401, detail="Authentication required")
    review = crud.get_review_by_id(review_id, u["id"])
    if not review:
        raise HTTPException(status_code=404, detail="Review not found or unauthorized")
    return {"success": True, "review": review}


@app.delete("/api/reviews/{review_id}")
def delete_single_review_endpoint(review_id: str, request: Request):
    """
    Deletes a single review record owned by the authenticated user.
    """
    u = get_request_user(request)
    if not u["id"]:
        raise HTTPException(status_code=401, detail="Authentication required")
    deleted = crud.delete_review(review_id, u["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Review not found or unauthorized")
    return {"success": True, "message": "Review deleted successfully"}


@app.delete("/api/reviews")
def clear_all_reviews_endpoint(request: Request):
    """
    Clears all review records owned by the authenticated user.
    """
    u = get_request_user(request)
    if not u["id"]:
        raise HTTPException(status_code=401, detail="Authentication required")
    count = crud.delete_all_reviews(u["id"])
    return {"success": True, "deleted_count": count}


# ============================================================
# UPLOADED FILES DATABASE ENDPOINTS
# ============================================================

@app.get("/api/files")
def get_user_files_endpoint(request: Request):
    """
    Returns list of uploaded files belonging to the authenticated user.
    """
    u = get_request_user(request)
    if not u["id"]:
        raise HTTPException(status_code=401, detail="Authentication required to view files")
    files = crud.get_user_files(u["id"])
    return {"success": True, "files": files}


@app.delete("/api/files/{file_id}")
def delete_user_file_endpoint(file_id: str, request: Request):
    """
    Deletes an uploaded file entry owned by the authenticated user.
    """
    u = get_request_user(request)
    if not u["id"]:
        raise HTTPException(status_code=401, detail="Authentication required")
    deleted = crud.delete_uploaded_file(file_id, u["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="File record not found or unauthorized")
    return {"success": True, "message": "File record deleted successfully"}


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "message": "AI Code Review Assistant API is running",
        "version": "1.4.0"
    }


@app.get("/")
def home():
    index_file = FRONTEND_BUILD_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    return {
        "success": True,
        "message": (
            "AI Code Review Assistant "
            "Backend Running Successfully"
        ),
        "version": "1.4.0"
    }


# ============================================================
# PROJECT INFORMATION
# ============================================================

@app.get("/project-info")
def project_info():

    metadata = (
        rag_pipeline
        .get_project_metadata()
    )

    if not metadata:

        raise HTTPException(
            status_code=404,
            detail=(
                "No project is currently indexed."
            )
        )

    # Infer input type if missing
    input_type = metadata.get("input_type")
    project_path = metadata.get("project_path", "")
    if not input_type:
        proj_str = str(project_path).lower().replace("\\", "/")
        if "pasted_code" in proj_str:
            input_type = "pasted_code"
        elif "temp_project" in proj_str or "uploaded_files" in proj_str:
            input_type = "source_file"
        else:
            input_type = "zip"
        metadata["input_type"] = input_type

    orig_name = metadata.get("original_filename")
    if not orig_name:
        files = metadata.get("files", [])
        if files and len(files) == 1:
            orig_name = files[0].get("name", "source_code.txt")
        else:
            orig_name = f"{metadata.get('project_name', 'project')}.zip"
        metadata["original_filename"] = orig_name

    return {
        "success": True,
        "project": metadata,
        "input_type": input_type,
        "original_filename": orig_name
    }


# ============================================================
# DYNAMIC PROJECT DOWNLOAD
# ============================================================

@app.get("/api/download/project")
def download_project():
    """
    Dynamically serves the complete analyzed project download matching the input type:
    - zip: complete ZIP project preserving folder structure and all actual project files.
    - source_file: actual uploaded source file with original filename and extension.
    - pasted_code: actual pasted source code with correct extension.
    """
    metadata = rag_pipeline.get_project_metadata()
    if not metadata:
        raise HTTPException(status_code=404, detail="No project is currently indexed for download.")

    input_type = metadata.get("input_type")
    project_path_str = metadata.get("project_path", "")
    
    # Fallback to discover directory if not set
    if not project_path_str or not os.path.exists(project_path_str):
        if os.path.exists("extracted"):
            subdirs = [p for p in Path("extracted").iterdir() if p.is_dir()]
            if subdirs:
                project_path_str = str(subdirs[0])
        if not project_path_str and os.path.exists("uploads/temp_project"):
            project_path_str = "uploads/temp_project"
        if not project_path_str and os.path.exists("uploads/pasted_code"):
            project_path_str = "uploads/pasted_code"

    if not project_path_str or not os.path.exists(project_path_str):
        raise HTTPException(status_code=404, detail="Project directory could not be located on disk.")

    proj_dir = Path(project_path_str)
    
    # Infer input_type if needed
    if not input_type:
        proj_str = str(proj_dir).lower().replace("\\", "/")
        if "pasted_code" in proj_str:
            input_type = "pasted_code"
        elif "temp_project" in proj_str or "uploaded_files" in proj_str:
            input_type = "source_file"
        else:
            input_type = "zip"

    # Case 1: Pasted code
    if input_type == "pasted_code":
        files = [p for p in proj_dir.glob("*") if p.is_file()]
        if not files:
            raise HTTPException(status_code=404, detail="Pasted code file not found.")
        file_to_send = files[0]
        filename = metadata.get("original_filename") or file_to_send.name
        return FileResponse(
            path=str(file_to_send),
            filename=filename,
            media_type="text/plain"
        )

    # Case 2: Single source file
    if input_type == "source_file":
        files = [p for p in proj_dir.glob("*") if p.is_file()]
        if files:
            file_to_send = files[0]
            filename = metadata.get("original_filename") or file_to_send.name
            return FileResponse(
                path=str(file_to_send),
                filename=filename,
                media_type="text/plain"
            )

    # Case 3: ZIP upload or multiple files -> package as complete ZIP preserving folder structure
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in proj_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(proj_dir)
                zf.write(file_path, arcname=str(arcname))
    
    zip_buffer.seek(0)
    zip_filename = metadata.get("original_filename") or f"{metadata.get('project_name', 'project')}.zip"
    if not zip_filename.lower().endswith(".zip"):
        zip_filename += ".zip"

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"'
        }
    )


@app.post("/api/download/code")
def download_custom_code(data: DownloadCodeRequest):
    """
    Directly downloads specific source code with the requested filename and extension.
    """
    safe_name = Path(data.filename).name or "code.txt"
    return Response(
        content=data.code,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"'
        }
    )


# ============================================================
# UPLOAD PROJECT
# ============================================================

@app.post("/upload-project")
async def upload_project(
    request: Request,
    file: UploadFile = File(...)
):

    try:

        if not file.filename:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Please select a ZIP project."
                )
            )

        if not file.filename.lower().endswith(
            ".zip"
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Only ZIP project files "
                    "are supported."
                )
            )

        # Security check: validate file size, type, and safety
        await validate_uploaded_file(file, is_zip=True)

        res = await (
            upload_service
            .process_zip_upload(
                file
            )
        )

        # Track in SQLite if user is authenticated
        u = get_request_user(request)
        if u["id"]:
            try:
                saved_path = str(UPLOAD_DIR / file.filename)
                fsize = os.path.getsize(saved_path) if os.path.exists(saved_path) else 0
                crud.create_uploaded_file(
                    file_id=str(uuid.uuid4()),
                    user_id=u["id"],
                    file_name=file.filename,
                    file_path=saved_path,
                    file_size=fsize,
                    file_type="zip"
                )
                print(f"[DB] Uploaded ZIP tracked in SQLite for user {u['id']}")
            except Exception as db_err:
                print(f"[DB] Error recording ZIP upload: {repr(db_err)}")

        return res

    except HTTPException:

        raise

    except Exception as e:

        print(
            "Upload Project Error:",
            repr(e)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to upload project."
            )
        )

    finally:

        try:

            await file.close()

        except Exception:

            pass


# ============================================================
# UPLOAD MULTIPLE SOURCE FILES
# ============================================================

@app.post("/upload-files")
async def upload_files(
    request: Request,
    files: List[UploadFile] = File(...)
):

    try:

        if not files:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Please select at least "
                    "one source file."
                )
            )

        # Security check: validate each source file
        for f in files:
            await validate_uploaded_file(f, is_zip=False)

        res = await (
            upload_service
            .process_multiple_files(
                files
            )
        )

        # Track in SQLite if user is authenticated
        u = get_request_user(request)
        if u["id"]:
            try:
                for f in files:
                    clean_name = sanitize_filename(f.filename)
                    saved_path = str(UPLOAD_DIR / clean_name)
                    fsize = os.path.getsize(saved_path) if os.path.exists(saved_path) else 0
                    crud.create_uploaded_file(
                        file_id=str(uuid.uuid4()),
                        user_id=u["id"],
                        file_name=clean_name,
                        file_path=saved_path,
                        file_size=fsize,
                        file_type=Path(clean_name).suffix or "code"
                    )
                print(f"[DB] Uploaded {len(files)} files tracked in SQLite for user {u['id']}")
            except Exception as db_err:
                print(f"[DB] Error recording uploaded files: {repr(db_err)}")

        return res

    except HTTPException:

        raise

    except Exception as e:

        print(
            "Upload Files Error:",
            repr(e)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to upload source files."
            )
        )

    finally:

        for file in files:

            try:

                await file.close()

            except Exception:

                pass


# ============================================================
# PASTE CODE
# ============================================================

@app.post("/paste-code")
def paste_code(
    data: PasteCodeRequest,
    request: Request
):

    try:

        filename = (
            data.filename.strip()
        )

        code = (
            data.code.strip()
        )

        if not filename:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Filename cannot be empty."
                )
            )

        if not code:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Code cannot be empty."
                )
            )

        # Security check on pasted file extension
        is_valid, err_msg = validate_file_extension(filename, allow_zip=False)
        if not is_valid:
            raise HTTPException(status_code=400, detail=err_msg)

        result = (
            upload_service
            .process_paste_code(
            code=code,
            filename=filename
            )
        )    

        # Track in SQLite if user is authenticated
        u = get_request_user(request)
        if u["id"]:
            try:
                clean_name = sanitize_filename(filename)
                crud.create_uploaded_file(
                    file_id=str(uuid.uuid4()),
                    user_id=u["id"],
                    file_name=clean_name,
                    file_path=str(EXTRACT_DIR / clean_name),
                    file_size=len(code.encode("utf-8")),
                    file_type=Path(clean_name).suffix or "code"
                )
                print(f"[DB] Pasted code tracked in SQLite for user {u['id']}")
            except Exception as db_err:
                print(f"[DB] Error recording pasted code: {repr(db_err)}")    
        print(
            "\n========== AFTER PASTE INDEX =========="
            )
        print(
            "Indexed Files:",
            rag_pipeline.get_indexed_files()
            )
        print(
            "Indexed File Count:",
            len(
                rag_pipeline.get_indexed_files()
                )
            )
        print(
            "Indexed Chunks:",
            rag_pipeline.vector_store.size()
            )
        print(
            "=======================================\n"
            )
        return result

    except HTTPException:

        raise

    except Exception as e:

        print(
            "Paste Code Error:",
            repr(e)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to process pasted code."
            )
        )


# ============================================================
# UPLOAD GITHUB REPOSITORY
# ============================================================

@app.post("/upload-github")
async def upload_github(
    data: GithubRequest
):

    try:

        repo_url = data.repo_url.strip()

        if not repo_url:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Repository URL "
                    "cannot be empty."
                )
            )

        return await (
            upload_service
            .process_github_repo(
                repo_url
            )
        )

    except HTTPException:

        raise

    except Exception as e:

        print(
            "Upload GitHub Error:",
            repr(e)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to download "
                "GitHub repository."
            )
        )


# ============================================================
# REVIEW PROJECT
# ============================================================

@app.post("/review")
def review_project(
    data: ReviewRequest,
    request: Request
):

    try:

        # ====================================================
        # QUESTION
        # ====================================================

        question = (
            data.question.strip()
        )

        if not question:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Review question "
                    "cannot be empty."
                )
            )

        # ====================================================
        # VECTOR DATABASE
        # ====================================================

        if not (
            rag_pipeline
            .vector_database_exists()
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Please upload a "
                    "project first."
                )
            )

        # ====================================================
        # REVIEW TYPES
        # ====================================================

        detected_modes = (
            rag_pipeline
            .prompt_builder
            .detect_review_modes(
                question
            )
        )

        print(
            "\nDetected Review Types:",
            detected_modes
        )

        # ====================================================
        # RETRIEVE FIRST
        # ====================================================

        print(
            "\nRetrieving relevant code..."
        )
        
        print(
            "\n========== REVIEW VECTOR STATE =========="
        )

        print(
            "Indexed Files:",
            rag_pipeline.get_indexed_files()
            )

        print(
            "Indexed File Count:",
            len(
                rag_pipeline.get_indexed_files()
            )
        )

        print(
            "Indexed Chunks:",
            rag_pipeline.vector_store.size()
        )

        print(
            "=========================================\n"
        )

        retrieval = (
            rag_pipeline
            .retrieve_context(
                query=question
            )
        )

        retrieved_chunks = (
            retrieval.get(
                "chunks",
                []
            )
        )

        query_type = retrieval.get(
            "query_type",
            "targeted"
        )

        print(
            "\nReview Query Type:",
            query_type
        )

        print(
            "Retrieved Chunks:",
            len(
                retrieved_chunks
            )
        )

        # ====================================================
        # TRUSTED FILES
        # ====================================================

        trusted_files = (
            build_trusted_files_analyzed(
                retrieved_chunks
            )
        )

        print(
            "\n========== TRUSTED CURRENT FILES =========="
        )

        for file_info in trusted_files:

            print(
                file_info.file_name,
                "|",
                file_info.path,
                "|",
                file_info.language
            )

        print(
            "Trusted File Count:",
            len(trusted_files)
        )

        print(
            "===========================================\n"
        )

        # ====================================================
        # NO RETRIEVED CODE
        # ====================================================

        if not retrieved_chunks:

            raise HTTPException(
                status_code=502,
                detail=(
                    "No relevant source code "
                    "was retrieved for this review."
                )
            )

        # ====================================================
        # GENERATE PROMPT FROM SAME RETRIEVAL
        # ====================================================

        prompt = (
            rag_pipeline
            .prompt_builder
            .build_prompt(
                query=question,
                retrieved_chunks=retrieved_chunks,
                project_metadata=(
                    rag_pipeline
                    .get_project_metadata()
                )
            )
        )

        print(
            "\nPrompt generated successfully."
        )

        print(
            "Prompt Characters:",
            len(prompt)
        )

        print(
            "Estimated Prompt Tokens:",
            len(prompt) // 4
        )

        # ====================================================
        # GROQ
        # ====================================================
        print("\n========== PROMPT DEBUG ==========")
        print("Prompt characters:", len(prompt))
        print("Prompt preview:")
        print(prompt[:3000])
        print("==================================")

        groq_messages = [
            {
                "role": "system",
                "content": (
                    "You are a senior software engineer performing a grounded code review.\n"
                    "Analyze ONLY the source code provided in the user prompt.\n\n"
                    "CRITICAL ROOT JSON FORMAT:\n"
                    "You MUST return the complete Structured Review JSON object at the root, containing ALL required keys:\n"
                    "project, question, user_requirements, review_types, answer_summary, files_analyzed, "
                    "key_methods, key_classes, libraries, bugs, errors, performance, security, code_quality, "
                    "corrected_code, expected_output, score, confidence, final_verdict.\n"
                    "DO NOT output an individual finding object as the root JSON. Place each finding inside its category array "
                    "(bugs, errors, security.issues, performance.issues, or code_quality.suggestions).\n\n"
                    "EIGHT-POINT SOLUTION SPECIFICATION (MANDATORY FOR EVERY ISSUE):\n"
                    "For EVERY detected issue across bugs, errors, security, performance, and code quality, you MUST provide:\n"
                    "1. title: Problem Identification\n"
                    "2. file, line, line_range: Exact File and Line Number\n"
                    "3. description & explanation: Why the code is problematic\n"
                    "4. severity: 'critical', 'high', 'medium', or 'low'\n"
                    "5. suggested_solution & fix: How the issue can be fixed\n"
                    "6. before_code: Problematic snippet from the original source\n"
                    "7. after_code & corrected_code: Corrected version of the code snippet\n"
                    "8. reason_for_correction: Why the corrected code is safer, better, or more efficient\n\n"
                    "For security issues, hardcoded passwords, tokens, or printed secrets MUST be reported under security.issues with high or critical severity.\n"
                    "Keep your response accurate, grounded, and matching the complete schema."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ]

        # Determine requested model or default
        requested_model = getattr(data, "model", None) or DEFAULT_GROQ_MODEL
        model_priority = [requested_model] + [
            m["id"] for m in AVAILABLE_GROQ_MODELS if m["id"] != requested_model
        ]

        raw_answer = None
        active_model_used = None
        last_error = None

        for target_model in model_priority:
            active_model_used = target_model
            is_openai = "openai" in target_model
            max_toks = 2048 if target_model == "qwen/qwen3.8-27b" else 4096
            extra_args = {"reasoning_effort": "low"} if is_openai else {}

            print(f"\n[GROQ] Querying model: {target_model} (max_tokens={max_toks})...")
            try:
                # 1. Attempt strict json_schema
                try:
                    response = client.chat.completions.create(
                        model=target_model,
                        temperature=0.1,
                        max_completion_tokens=max_toks,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "name": "structured_code_review",
                                "strict": True,
                                "schema": GROQ_REVIEW_SCHEMA
                            }
                        },
                        messages=groq_messages,
                        **extra_args
                    )
                    raw_answer = response.choices[0].message.content
                except Exception as schema_err:
                    err_text = str(schema_err).lower()
                    if "429" in err_text or "rate_limit" in err_text:
                        raise schema_err

                    # Check if failed_generation exists in the error body to recover generated content directly
                    err_dict = getattr(schema_err, "body", None) or {}
                    if isinstance(err_dict, dict) and "error" in err_dict and isinstance(err_dict["error"], dict) and "failed_generation" in err_dict["error"]:
                        raw_answer = err_dict["error"]["failed_generation"]
                        print(f"[GROQ] Extracted failed_generation from {target_model} schema error.")

                    # Fallback to json_object mode on same model
                    if not raw_answer:
                        print(f"[GROQ] Retrying {target_model} with response_format={{'type': 'json_object'}}...")
                        fallback_response = client.chat.completions.create(
                            model=target_model,
                            temperature=0.1,
                            max_completion_tokens=max_toks,
                            response_format={"type": "json_object"},
                            messages=groq_messages,
                            **extra_args
                        )
                        raw_answer = fallback_response.choices[0].message.content

                if raw_answer and raw_answer.strip():
                    print(f"[GROQ] Successfully generated review using {target_model}!")
                    break

            except Exception as model_err:
                last_error = model_err
                err_text = str(model_err).lower()
                if "429" in err_text or "rate_limit" in err_text:
                    print(f"[GROQ] Rate limit encountered on {target_model} (429). Failing over to next available model...")
                    continue
                else:
                    print(f"[GROQ] Error with {target_model}: {repr(model_err)}. Failing over to next model in pool...")
                    continue

        # ====================================================
        # RAW RESPONSE
        # ====================================================

        if not raw_answer:
            if last_error and ("429" in str(last_error).lower() or "rate_limit" in str(last_error).lower()):
                raise HTTPException(
                    status_code=429,
                    detail="AI model rate limit reached across all available models. Please try again in 30 seconds."
                )
            raise HTTPException(
                status_code=502,
                detail=f"All AI models failed to generate response: {repr(last_error)}"
            )

        print(
            "\nStructured AI response received."
        )

        # ====================================================
        # CLEAN
        # ====================================================

        cleaned_answer = (
            clean_json_response(
                raw_answer
            )
        )

        # ====================================================
        # PARSE
        # ====================================================

        try:

            review_json = json.loads(
                cleaned_answer
            )

        except json.JSONDecodeError as e:

            print(
                "\nINVALID GROQ JSON"
            )

            print(
                cleaned_answer
            )

            print(
                "\nJSON ERROR:",
                str(e)
            )

            raise HTTPException(
                status_code=502,
                detail=(
                    "The AI model returned "
                    "invalid JSON."
                )
            )

        # ====================================================
        # ROBUST PRE-NORMALIZATION
        # ====================================================

        review_json = robust_pre_normalize(review_json)

        # ====================================================
        # CRITICAL SECURITY / ACCURACY FIX
        # ====================================================
        #
        # NEVER TRUST LLM FILE LIST.
        #
        # The backend owns this field.
        #
        # ====================================================

        review_json[
            "files_analyzed"
        ] = [
            file_info.model_dump()
            for file_info
            in trusted_files
        ]

        # ====================================================
        # TRUSTED PROJECT INFORMATION
        # ====================================================

        review_json[
            "project"
        ] = build_trusted_project_info(
            retrieved_chunks,
            rag_pipeline
            .get_project_metadata()
        )

        # ====================================================
        # TRUSTED QUESTION
        # ====================================================

        review_json[
            "question"
        ] = question

        # ====================================================
        # TRUSTED REVIEW TYPES
        # ====================================================

        review_json[
            "review_types"
        ] = sorted(
            list(
                detected_modes
            )
        )

        # ====================================================
        # PYDANTIC VALIDATION
        # ====================================================

        try:

            validated_review = (
                StructuredReview
                .model_validate(
                    review_json
                )
            )

        except ValidationError as e:

            print(
                "\nREVIEW VALIDATION ERROR"
            )

            print(
                e
            )

            print(
                "\nRECEIVED JSON:"
            )

            print(
                json.dumps(
                    review_json,
                    indent=2,
                    ensure_ascii=False
                )
            )

            raise HTTPException(
                status_code=502,
                detail=(
                    "The AI review did not "
                    "match the required "
                    "response structure."
                )
            )

        # ====================================================
        # FINDING VALIDATION
        # ====================================================

        validated_review = (
            validate_findings(
                validated_review
            )
        )

        # ====================================================
        # NORMALIZE
        # ====================================================

        validated_review = (
            normalize_review(
                review=validated_review,
                question=question
            )
        )

        # ====================================================
        # REVIEW MODES
        # ====================================================

        modes = set(
            validated_review.review_types
        )

        full_review = (
            "full_review"
            in modes
        )

        # ====================================================
        # OPTIONAL SECTIONS
        # ====================================================

        if (
            "performance"
            not in modes
            and not full_review
        ):

            validated_review.performance = None

        if (
            "security"
            not in modes
            and not full_review
        ):

            validated_review.security = None

        if (
            "code_quality"
            not in modes
            and not full_review
        ):

            validated_review.code_quality = None

        if (
            "output"
            not in modes
            and not full_review
        ):

            validated_review.expected_output = None

        # ====================================================
        # SCORE
        # ====================================================

        score_keywords = [
            "score",
            "rating",
            "rate this",
            "code quality score",
            "project score"
        ]

        score_requested = any(
            keyword
            in question.lower()
            for keyword in score_keywords
        )

        if not score_requested:

            validated_review.score = None

        # ====================================================
        # FINAL NORMALIZATION
        # ====================================================

        validated_review = (
            normalize_review(
                review=validated_review,
                question=question
            )
        )

        # ====================================================
        # FINAL FILE OVERRIDE
        # ====================================================
        #
        # Even after normalization, force the authoritative
        # current retrieval files one final time.
        #
        # ====================================================

        validated_review.files_analyzed = (
            trusted_files
        )

        # ====================================================
        # FINAL DEBUG
        # ====================================================

        print(
            "\n========== FINAL REVIEW FILES =========="
        )

        for file_info in (
            validated_review.files_analyzed
        ):

            print(
                file_info.file_name,
                "|",
                file_info.path
            )

        print(
            "Final File Count:",
            len(
                validated_review.files_analyzed
            )
        )

        print(
            "========================================\n"
        )

        # ====================================================
        # RESPONSE & SQLITE PERSISTENCE
        # ====================================================

        u = get_request_user(request)
        review_id = str(uuid.uuid4())

        if u["id"]:
            try:
                proj_name = (
                    validated_review.project.name
                    if validated_review.project and validated_review.project.name
                    else "Code Review"
                )
                proj_langs = (
                    ", ".join(validated_review.project.languages)
                    if validated_review.project and validated_review.project.languages
                    else "Source"
                )
                bugs_cnt = len(validated_review.bugs) if validated_review.bugs else 0
                sec_cnt = validated_review.security.issues_found if validated_review.security else 0
                perf_cnt = len(validated_review.performance.issues) if (validated_review.performance and validated_review.performance.issues) else 0
                qual_cnt = 0
                if validated_review.code_quality:
                    qual_cnt = len(validated_review.code_quality.observations or []) + len(validated_review.code_quality.suggestions or [])
                total_issues = bugs_cnt + sec_cnt + perf_cnt + qual_cnt

                crud.create_review(
                    review_id=review_id,
                    user_id=u["id"],
                    project_name=proj_name,
                    language=proj_langs,
                    question=question,
                    score=getattr(validated_review, "score", None),
                    confidence=getattr(validated_review, "confidence", None),
                    issue_count=total_issues,
                    bugs_count=bugs_cnt,
                    security_count=sec_cnt,
                    performance_count=perf_cnt,
                    quality_count=qual_cnt,
                    raw_review=validated_review.model_dump()
                )
                print(f"[DB] Review saved to SQLite for user {u['id']}: {review_id}")
            except Exception as db_err:
                print(f"[DB] Error saving review to SQLite: {repr(db_err)}")

        return {
            "success": True,
            "id": review_id,
            "question": question,
            "review_types": (
                validated_review
                .review_types
            ),
            "model_used": active_model_used,
            "review": (
                validated_review
                .model_dump()
            )
        }

    # ========================================================
    # HTTP EXCEPTIONS
    # ========================================================

    except HTTPException:

        raise

    # ========================================================
    # GROQ / GENERAL ERRORS
    # ========================================================

    except Exception as e:

        error_text = str(e)

        print(
            "\nReview Error:",
            repr(e)
        )

        # ----------------------------------------------------
        # JSON VALIDATION
        # ----------------------------------------------------

        if (
            "json_validate_failed"
            in error_text.lower()
            or
            "failed to validate json"
            in error_text.lower()
        ):

            raise HTTPException(
                status_code=502,
                detail=(
                    "The AI model could not "
                    "generate a response matching "
                    "the structured review schema."
                )
            )

        # ----------------------------------------------------
        # RATE LIMIT
        # ----------------------------------------------------

        if (
            "429"
            in error_text
            or
            "rate_limit"
            in error_text.lower()
        ):

            raise HTTPException(
                status_code=429,
                detail=(
                    "AI model rate limit reached. "
                    "Please try again shortly."
                )
            )

        # ----------------------------------------------------
        # AUTHENTICATION
        # ----------------------------------------------------

        if (
            "401"
            in error_text
            or
            "authentication"
            in error_text.lower()
            or
            "invalid api key"
            in error_text.lower()
        ):

            raise HTTPException(
                status_code=502,
                detail=(
                    "AI provider authentication failed. "
                    "Check GROQ_API_KEY in .env."
                )
            )

        # ----------------------------------------------------
        # MODEL
        # ----------------------------------------------------

        if (
            "model_not_found"
            in error_text.lower()
            or
            "does not exist"
            in error_text.lower()
        ):

            raise HTTPException(
                status_code=502,
                detail=(
                    "The configured Groq model is "
                    "not available to this API key."
                )
            )

        # ----------------------------------------------------
        # REQUEST TOO LARGE
        # ----------------------------------------------------

        if (
            "413"
            in error_text
            or
            "request too large"
            in error_text.lower()
        ):

            raise HTTPException(
                status_code=413,
                detail=(
                    "The retrieved code and prompt "
                    "are too large for the current "
                    "AI model limit."
                )
            )

        # ----------------------------------------------------
        # GENERIC
        # ----------------------------------------------------

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to generate "
                "code review."
            )
        )


# ============================================================
# SPA CLIENT-SIDE FALLBACK ROUTE
# ============================================================

@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    target = FRONTEND_BUILD_DIR / full_path
    if full_path and target.exists() and target.is_file():
        return FileResponse(target)

    index_file = FRONTEND_BUILD_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    raise HTTPException(status_code=404, detail="Page not found")