import os
import shutil
import zipfile
from pathlib import Path

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from groq import Groq
from rag.pipeline import RAGPipeline
# ===========================
# Load Environment Variables
# ===========================

load_dotenv()

API_KEY = os.getenv("GROQ_API_KEY")

if not API_KEY:
    raise Exception("GROQ_API_KEY not found in .env")

# ===========================
# Configure Groq
# ===========================

client = Groq(api_key=API_KEY)
rag_pipeline = RAGPipeline()
# ===========================
# FastAPI App
# ===========================

app = FastAPI(title="AI Code Review Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===========================
# Project Directories
# ===========================

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

EXTRACT_DIR = Path("extracted")
EXTRACT_DIR.mkdir(exist_ok=True)

# ===========================
# Request Model
# ===========================

class CodeRequest(BaseModel):
    code: str

# ===========================
# Home API
# ===========================

@app.get("/")
def home():
    return {
        "message": "AI Code Review Assistant Backend Running Successfully"
    }

# ===========================
# Upload Project API
# ===========================

@app.post("/upload-project")
async def upload_project(file: UploadFile = File(...)):
    try:

        # Accept only ZIP files
        if not file.filename.endswith(".zip"):
            raise HTTPException(
                status_code=400,
                detail="Please upload a ZIP file."
            )

        # Save uploaded ZIP
        zip_path = UPLOAD_DIR / file.filename

        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Create project extraction folder
        project_name = Path(file.filename).stem
        project_folder = EXTRACT_DIR / project_name

        # Remove old extracted folder if it exists
        if project_folder.exists():
            shutil.rmtree(project_folder)

        project_folder.mkdir(parents=True, exist_ok=True)

        # Extract ZIP
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(project_folder)
        # Build FAISS vector database
        rag_pipeline.build_vector_database(str(project_folder))
        return {
            "success": True,
            "message": "Project uploaded and extracted successfully.",
            "project_name": project_name,
            "zip_path": str(zip_path),
            "extract_path": str(project_folder)
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ===========================
# Code Review API
# ===========================

@app.post("/review")
def review_code(data: CodeRequest):

    try:

        prompt = f"""
You are an Expert AI Code Review Assistant.

Analyze ONLY the given source code.

Source Code:
----------------
{data.code}
----------------

Rules:
- Review only the provided code.
- Carefully check the code for actual problems.
- Check carefully for syntax errors.
- Check for missing brackets, braces, parentheses, and semicolons where required.
- Check for compilation errors.
- Check for runtime errors.
- Check for undefined variables or functions.
- Check for logical errors.
- Give the score based only on actual problems in the code.
- Use simple English.
- Keep every section short.
- Each section must contain exactly 2 simple sentences.
- Each sentence must be on a separate line.
- Do not use emojis.
- Do not give a percentage score.
- The Overall Score must be out of 10.
- Do not reduce the score for optional improvements.
- Do not reduce the score because the code is simple.
- Do not reduce the score for alternative coding styles.
- Do not reduce the score for suggestions that are not actual problems.

Scoring Rules:
- 10/10: The code is syntactically correct, compiles successfully, works correctly, and has no actual bugs, security issues, performance problems, or serious code quality problems.
- 9/10: The code works correctly but has one very minor actual issue.
- 8/10: The code works but has some minor actual issues.
- 7/10 or lower: The code has significant bugs, errors, or multiple actual problems.
- If the code contains any syntax error or compilation error, NEVER give 10/10.
- If the code contains a real bug, NEVER give 10/10.
- Optional suggestions alone must not reduce the score.

Format:

Summary:
Write 2 simple sentences about what the code does.

Bugs:
Write 2 simple sentences about errors or problems.
If there are no bugs:
No major bugs found.
The code works correctly.

Security:
Write 2 simple sentences about security.
If there are no security issues:
No security issues found.
The code is safe.

Performance:
Write 2 simple sentences about performance.

Code Quality:
Write 2 simple sentences about readability and maintainability.

Best Practices:
Write 2 simple sentences about coding improvements.

Suggestions:
Write 2 simple sentences about possible improvements.

Overall Score:
Give only one score out of 10 based on the actual code.
If the code contains any syntax error, compilation error, runtime error, or real bug, do not give 10/10.
If the code is fully correct and has no actual problems, give 10/10.
Use this exact format:
Overall Score: X/10

Code to review:

{data.code}
"""

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return {
            "review": response.choices[0].message.content
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )