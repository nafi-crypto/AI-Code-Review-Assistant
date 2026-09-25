# backend/rag/pipeline.py

import json
import os
from typing import Dict, List, Optional

from .loader import ProjectLoader
from .chunker import CodeChunker
from .embedder import CodeEmbedder
from .vector_store import VectorStore
from .retriever import Retriever
from .prompt_builder import PromptBuilder


class RAGPipeline:
    """
    Main RAG pipeline for AI Code Review Assistant.

    Flow:

        Project
            ↓
        Loader
            ↓
        Chunker
            ↓
        Embedder
            ↓
        Fresh VectorStore
            ↓
        Retriever
            ↓
        Query Classification
            ↓
        Retrieval
            ↓
        Prompt Builder
            ↓
        LLM
    """

    # ============================================================
    # Persistent paths
    # ============================================================

    VECTOR_DB_DIR = "vector_db"

    INDEX_PATH = os.path.join(
        VECTOR_DB_DIR,
        "faiss.index"
    )

    METADATA_PATH = os.path.join(
        VECTOR_DB_DIR,
        "metadata.pkl"
    )

    PROJECT_METADATA_PATH = os.path.join(
        VECTOR_DB_DIR,
        "project_metadata.json"
    )

    # ============================================================
    # Project-wide query phrases
    # ============================================================

    PROJECT_WIDE_PHRASES = (
        "comprehensive review",
        "comprehensive code review",
        "comprehensive analysis",
        "comprehensive security and code review",

        "complete analysis",
        "complete review",
        "complete code review",
        "complete project review",

        "full analysis",
        "full review",
        "full code review",

        "entire project",
        "whole project",
        "complete project",
        "entire codebase",
        "whole codebase",

        "all files",
        "every file",
        "all bugs",
        "all errors",
        "find all bugs",
        "find all errors",

        "analyze project",
        "analyse project",
        "analyze the project",
        "analyse the project",

        "review project",
        "review the project",

        "analyze everything",
        "analyse everything",
        "review everything",

        "analyze the entire file",
        "analyse the entire file",
        "review the entire file",
        "complete file review",
        "full file review",
    )

    # ============================================================
    # Constructor
    # ============================================================

    def __init__(self):

        print(
            "\nInitializing RAG Pipeline...\n"
        )

        self.loader: Optional[
            ProjectLoader
        ] = None

        self.chunker = CodeChunker()

        self.embedder = CodeEmbedder()

        # --------------------------------------------------------
        # Pipeline owns exactly one active VectorStore.
        # --------------------------------------------------------

        self.vector_store = VectorStore()

        self.prompt_builder = PromptBuilder()

        self.project_metadata = None

        self.retriever: Optional[
            Retriever
        ] = None

        # --------------------------------------------------------
        # Restore last persisted project after server restart.
        # --------------------------------------------------------

        if self.vector_database_exists():

            print(
                "Existing vector database found."
            )

            try:

                self.vector_store.load(
                    index_path=self.INDEX_PATH,
                    metadata_path=self.METADATA_PATH
                )

                self._create_retriever()

                print(
                    "Existing vector database "
                    "and retriever loaded successfully."
                )

            except Exception as e:

                print(
                    "Could not load existing "
                    "vector database:",
                    repr(e)
                )

                self.vector_store = VectorStore()

                self.retriever = None

        # --------------------------------------------------------
        # Load project metadata.
        # --------------------------------------------------------

        self.load_project_metadata()

        print(
            "\nRAG Pipeline Ready.\n"
        )

    # ============================================================
    # CREATE RETRIEVER
    # ============================================================

    def _create_retriever(self):
        """
        Create Retriever using THIS pipeline's VectorStore.

        This is critical for project isolation.

        The Retriever must not independently load an old
        vector_db/metadata.pkl when a fresh VectorStore is
        already available.
        """

        self.retriever = Retriever(
            vector_store=self.vector_store
        )

        # --------------------------------------------------------
        # Diagnostic verification
        # --------------------------------------------------------

        print(
            "\n========== RETRIEVER STATE =========="
        )

        print(
            "Pipeline VectorStore:",
            id(self.vector_store)
        )

        print(
            "Retriever VectorStore:",
            id(self.retriever.vector_store)
        )

        print(
            "Same VectorStore:",
            self.retriever.vector_store
            is self.vector_store
        )

        print(
            "Retriever chunks:",
            self.retriever.vector_store.size()
        )

        print(
            "Retriever files:",
            self.retriever.vector_store.get_indexed_files()
        )

        print(
            "=====================================\n"
        )

    # ============================================================
    # BUILD VECTOR DATABASE
    # ============================================================

    def build_vector_database(
        self,
        project_path: str,
        input_type: Optional[str] = None,
        original_filename: Optional[str] = None
    ):

        print(
            "\n=========================================="
        )

        print(
            "BUILDING NEW PROJECT INDEX"
        )

        print(
            "=========================================="
        )

        print(
            "Project Path:",
            project_path
        )

        # ========================================================
        # CRITICAL PROJECT RESET
        # ========================================================

        self.vector_store = VectorStore()

        self.retriever = None

        self.project_metadata = None

        # ========================================================
        # LOAD PROJECT
        # ========================================================

        print(
            "\nLoading project..."
        )

        self.loader = ProjectLoader(
            project_path
        )

        documents = self.loader.load()

        if not documents:

            raise ValueError(
                "No supported source-code files "
                "were found inside the uploaded project."
            )

        print(
            f"Loaded {len(documents)} files."
        )

        # ========================================================
        # PROJECT METADATA
        # ========================================================

        self.project_metadata = (
            self.loader.get_metadata()
        )

        print(
            "\nProject Metadata:"
        )

        print(
            "Project Name :",
            self.project_metadata.get(
                "project_name",
                "Unknown"
            )
        )

        print(
            "Total Files  :",
            self.project_metadata.get(
                "total_files",
                0
            )
        )

        print(
            "Total Lines  :",
            self.project_metadata.get(
                "total_lines",
                0
            )
        )

        print(
            "Languages    :",
            list(
                self.project_metadata.get(
                    "languages",
                    {}
                ).keys()
            )
        )

        if input_type is None:
            proj_str = str(project_path).lower().replace("\\", "/")
            if "pasted_code" in proj_str:
                input_type = "pasted_code"
            elif "temp_project" in proj_str or "uploaded_files" in proj_str:
                input_type = "source_file"
            else:
                input_type = "zip"

        self.project_metadata["project_path"] = str(project_path)
        self.project_metadata["input_type"] = input_type
        if original_filename:
            self.project_metadata["original_filename"] = original_filename
        elif "original_filename" not in self.project_metadata:
            files_list = self.project_metadata.get("files", [])
            if files_list and len(files_list) == 1:
                self.project_metadata["original_filename"] = files_list[0].get("name", "source_code.txt")
            else:
                self.project_metadata["original_filename"] = f"{self.project_metadata.get('project_name', 'project')}.zip"

        print(
            "Input Type   :",
            self.project_metadata.get("input_type")
        )
        print(
            "Original File:",
            self.project_metadata.get("original_filename")
        )

        # ========================================================
        # SAVE PROJECT METADATA
        # ========================================================

        self.save_project_metadata()

        # ========================================================
        # CHUNK
        # ========================================================

        print(
            "\nChunking..."
        )

        chunks = (
            self.chunker.chunk_documents(
                documents
            )
        )

        if not chunks:

            raise ValueError(
                "No source-code chunks were generated."
            )

        print(
            f"Generated {len(chunks)} chunks."
        )

        # ========================================================
        # EMBEDDINGS
        # ========================================================

        print(
            "\nGenerating embeddings..."
        )

        embedded_chunks = (
            self.embedder.embed_chunks(
                chunks
            )
        )

        if not embedded_chunks:

            raise ValueError(
                "No embeddings were generated."
            )

        # ========================================================
        # CREATE FRESH VECTOR STORE
        # ========================================================

        print(
            "\nCreating new FAISS index..."
        )

        self.vector_store.add_chunks(
            embedded_chunks
        )

        # ========================================================
        # DIAGNOSTIC: AFTER INDEXING
        # ========================================================

        print(
            "\n========== AFTER INDEXING =========="
        )

        print(
            "VectorStore chunks:",
            self.vector_store.size()
        )

        print(
            "VectorStore files:",
            self.vector_store.get_indexed_files()
        )

        print(
            "VectorStore object:",
            id(self.vector_store)
        )

        print(
            "====================================\n"
        )

        # ========================================================
        # SAVE CURRENT PROJECT
        # ========================================================

        self.vector_store.save(
            index_path=self.INDEX_PATH,
            metadata_path=self.METADATA_PATH
        )

        # ========================================================
        # CREATE RETRIEVER
        # ========================================================

        print(
            "\nCreating retriever..."
        )

        self._create_retriever()

        if self.retriever is None:

            raise RuntimeError(
                "Retriever could not be initialized."
            )

        # ========================================================
        # RETRIEVAL STATISTICS
        # ========================================================

        statistics = (
            self.get_retrieval_statistics()
        )

        print(
            "\n=========================================="
        )

        print(
            "RETRIEVAL STATISTICS"
        )

        print(
            "=========================================="
        )

        print(
            "Indexed Files :",
            statistics[
                "total_indexed_files"
            ]
        )

        print(
            "Total Chunks  :",
            statistics[
                "total_chunks"
            ]
        )

        print(
            "=========================================="
        )

        # ========================================================
        # INDEXED FILES
        # ========================================================

        indexed_files = (
            self.vector_store
            .get_indexed_files()
        )

        print(
            "\nIndexed Files:"
        )

        for file_path in indexed_files:

            print(
                " -",
                file_path
            )

        print(
            "\nNew project index created successfully."
        )

        return self.project_metadata

    # ============================================================
    # QUERY CLASSIFICATION
    # ============================================================

    def classify_query(
        self,
        query: str
    ) -> str:

        normalized_query = (
            query
            .strip()
            .lower()
        )

        # --------------------------------------------------------
        # Explicit project-wide phrases
        # --------------------------------------------------------

        for phrase in (
            self.PROJECT_WIDE_PHRASES
        ):

            if phrase in normalized_query:

                return "project_wide"

        # --------------------------------------------------------
        # Broad categories
        # --------------------------------------------------------

        broad_categories = (
            "bugs",
            "errors",
            "security",
            "performance",
            "quality",
            "architecture",
            "methods",
            "classes",
            "libraries",
            "output",
            "improvements",
        )

        category_count = sum(
            1
            for category in broad_categories
            if category in normalized_query
        )

        if category_count >= 4:

            return "project_wide"

        return "targeted"

    # ============================================================
    # RETRIEVE CONTEXT
    # ============================================================

    def retrieve_context(
        self,
        query: str,
        targeted_top_k: int = 3,
        project_max_chunks: int = 100,
        chunks_per_file: int = 10
    ) -> Dict:

        if self.retriever is None:
            self._create_retriever()

        if self.retriever is None:
            raise RuntimeError(
                "Retriever is not available."
            )

        query_type = self.classify_query(query)

        print(
            f"\nQuery Type: {query_type}"
        )

        # ========================================================
        # COMPLETE SOURCE MODE
        # ========================================================
        # For a small single-file project, send every chunk
        # to the LLM instead of performing semantic retrieval.
        # This prevents false findings caused by missing context.
        # ========================================================

        total_chunks = self.vector_store.size()
        total_files = self.vector_store.file_count()

        print(
            f"Indexed Files: {total_files}"
        )

        print(
            f"Indexed Chunks: {total_chunks}"
        )

        if total_files == 1 and total_chunks <= 10:

            print(
                "\nUsing COMPLETE SOURCE retrieval."
            )

            chunks = [
                chunk.copy()
                for chunk in self.vector_store.metadata
            ]

            chunks.sort(
                key=lambda chunk: (
                    chunk.get(
                        "relative_path",
                        chunk.get(
                            "path",
                            ""
                        )
                    ),
                    chunk.get(
                        "start_line",
                        0
                    )
                )
            )

            print(
                f"Complete source contains "
                f"{len(chunks)} chunks."
            )

            return {
                "query_type": "complete_source",
                "chunks": chunks
            }

        # ========================================================
        # PROJECT-WIDE
        # ========================================================

        if query_type == "project_wide":

            print(
                "Using broad project retrieval..."
            )

            chunks = (
                self.retriever
                .retrieve_project_wide(
                    query=query,
                    max_chunks=project_max_chunks,
                    chunks_per_file=chunks_per_file
                )
            )

        # ========================================================
        # TARGETED
        # ========================================================

        else:

            print(
                "Using targeted semantic retrieval..."
            )

            chunks = (
                self.retriever.retrieve(
                    query=query,
                    top_k=targeted_top_k
                )
            )

        return {
            "query_type": query_type,
            "chunks": chunks
        }
        # ========================================================
        # PROJECT-WIDE
        # ========================================================

        if query_type == "project_wide":

            print(
                "Using broad project retrieval..."
            )

            chunks = (
                self.retriever
                .retrieve_project_wide(
                    query=query,
                    max_chunks=project_max_chunks,
                    chunks_per_file=chunks_per_file
                )
            )

        # ========================================================
        # TARGETED
        # ========================================================

        else:

            print(
                "Using targeted semantic retrieval..."
            )

            chunks = (
                self.retriever.retrieve(
                    query=query,
                    top_k=targeted_top_k
                )
            )

        return {
            "query_type": query_type,
            "chunks": chunks
        }
    # ============================================================
    # GENERATE PROMPT
    # ============================================================

    def generate_prompt(
        self,
        query: str,
        targeted_top_k: int = 3,
        project_max_chunks: int = 8,
        chunks_per_file: int = 2
    ):

        if not query or not query.strip():

            raise ValueError(
                "Question cannot be empty."
            )

        query = query.strip()

        # ========================================================
        # VECTOR DATABASE CHECK
        # ========================================================

        if not self.vector_database_exists():

            raise ValueError(
                "No vector database found. "
                "Please upload a project first."
            )

        # ========================================================
        # RETRIEVER CHECK
        # ========================================================

        if self.retriever is None:

            print(
                "\nInitializing retriever..."
            )

            self.vector_store.load(
                index_path=self.INDEX_PATH,
                metadata_path=self.METADATA_PATH
            )

            self._create_retriever()

        # ========================================================
        # RETRIEVE
        # ========================================================

        print(
            "\nRetrieving relevant code..."
        )

        retrieval = (
            self.retrieve_context(
                query=query,
                targeted_top_k=targeted_top_k,
                project_max_chunks=project_max_chunks,
                chunks_per_file=chunks_per_file
            )
        )

        query_type = (
            retrieval["query_type"]
        )

        retrieved_chunks = (
            retrieval["chunks"]
        )

        print(
            f"\nRetrieved "
            f"{len(retrieved_chunks)} chunks."
        )

        # ========================================================
        # CRITICAL DIAGNOSTIC
        # ========================================================

        print(
            "\n========== FINAL RETRIEVAL =========="
        )

        retrieved_files = set()

        for i, chunk in enumerate(
            retrieved_chunks,
            start=1
        ):

            file_name = chunk.get(
                "name",
                "Unknown"
            )

            path = (
                chunk.get("relative_path")
                or chunk.get("path")
                or "Unknown"
            )

            retrieved_files.add(
                path
            )

            print(
                f"{i}. "
                f"{file_name} | "
                f"{path} | "
                f"Lines "
                f"{chunk.get('start_line', '?')}-"
                f"{chunk.get('end_line', '?')}"
            )

        print(
            "\nRetrieved Files:",
            sorted(retrieved_files)
        )

        print(
            "Retrieved File Count:",
            len(retrieved_files)
        )

        print(
            "=====================================\n"
        )

        # ========================================================
        # PRINT RETRIEVED CHUNKS
        # ========================================================

        self.print_retrieved_chunks(
            retrieved_chunks
        )

        # ========================================================
        # PROJECT METADATA
        # ========================================================

        if self.project_metadata is None:

            self.load_project_metadata()

        # ========================================================
        # PROMPT
        # ========================================================

        prompt = (
            self.prompt_builder.build_prompt(
                query=query,
                retrieved_chunks=retrieved_chunks,
                project_metadata=self.project_metadata
            )
        )

        print(
            f"\nPrompt generated using "
            f"{query_type} retrieval."
        )

        print(
            "Prompt Characters:",
            len(prompt)
        )

        return prompt

    # ============================================================
    # PRINT RETRIEVED CHUNKS
    # ============================================================

    def print_retrieved_chunks(
        self,
        retrieved_chunks: List[Dict]
    ):

        if not retrieved_chunks:

            print(
                "\nNo chunks retrieved."
            )

            return

        print(
            f"\nRetrieved "
            f"{len(retrieved_chunks)} chunks."
        )

        for i, chunk in enumerate(
            retrieved_chunks,
            start=1
        ):

            print(
                f"\nRetrieved Chunk {i}"
            )

            print(
                "File:",
                chunk.get(
                    "name",
                    "Unknown"
                )
            )

            print(
                "Path:",
                chunk.get(
                    "path",
                    "Unknown"
                )
            )

            print(
                "Language:",
                chunk.get(
                    "language",
                    "Unknown"
                )
            )

            print(
                "Lines:",
                f"{chunk.get('start_line', '?')} - "
                f"{chunk.get('end_line', '?')}"
            )

            distance = chunk.get(
                "distance"
            )

            if distance is not None:

                print(
                    "Distance:",
                    distance
                )

    # ============================================================
    # SAVE PROJECT METADATA
    # ============================================================

    def save_project_metadata(
        self,
        metadata_path=PROJECT_METADATA_PATH
    ):

        if self.project_metadata is None:

            return

        directory = os.path.dirname(
            metadata_path
        )

        if directory:

            os.makedirs(
                directory,
                exist_ok=True
            )

        with open(
            metadata_path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                self.project_metadata,
                file,
                indent=4
            )

        print(
            "Current project metadata saved."
        )

    # ============================================================
    # LOAD PROJECT METADATA
    # ============================================================

    def load_project_metadata(
        self,
        metadata_path=PROJECT_METADATA_PATH
    ):

        if not os.path.exists(
            metadata_path
        ):

            self.project_metadata = None

            return None

        try:

            with open(
                metadata_path,
                "r",
                encoding="utf-8"
            ) as file:

                self.project_metadata = (
                    json.load(file)
                )

            print(
                "Project metadata loaded."
            )

            return self.project_metadata

        except (
            OSError,
            json.JSONDecodeError
        ) as e:

            print(
                "Could not load "
                "project metadata:",
                repr(e)
            )

            self.project_metadata = None

            return None

    # ============================================================
    # VECTOR DATABASE EXISTS
    # ============================================================

    def vector_database_exists(
        self
    ) -> bool:

        return (
            os.path.exists(
                self.INDEX_PATH
            )
            and
            os.path.exists(
                self.METADATA_PATH
            )
        )

    # ============================================================
    # RETRIEVAL STATISTICS
    # ============================================================

    def get_retrieval_statistics(
        self
    ) -> Dict:

        total_chunks = (
            self.vector_store.size()
        )

        total_files = (
            self.vector_store.file_count()
        )

        return {
            "total_chunks": total_chunks,
            "total_indexed_files": total_files
        }

    # ============================================================
    # PROJECT METADATA GETTER
    # ============================================================

    def get_project_metadata(
        self
    ):

        if self.project_metadata is None:

            self.load_project_metadata()

        return self.project_metadata

    # ============================================================
    # CURRENT INDEXED FILES
    # ============================================================

    def get_indexed_files(
        self
    ) -> List[str]:

        return (
            self.vector_store
            .get_indexed_files()
        )


# ================================================================
# LOCAL TEST
# ================================================================

if __name__ == "__main__":

    rag = RAGPipeline()

    if not rag.vector_database_exists():

        print(
            "No vector database found."
        )

        print(
            "Build/upload a project first."
        )

    else:

        print(
            "Vector database found."
        )

        metadata = (
            rag.get_project_metadata()
        )

        if metadata:

            print(
                "\nProject Information"
            )

            print(
                "Project:",
                metadata.get(
                    "project_name"
                )
            )

            print(
                "Files:",
                metadata.get(
                    "total_files"
                )
            )

            print(
                "Lines:",
                metadata.get(
                    "total_lines"
                )
            )

            print(
                "Languages:",
                list(
                    metadata.get(
                        "languages",
                        {}
                    ).keys()
                )
            )

        statistics = (
            rag.get_retrieval_statistics()
        )

        print(
            "\nRetrieval Statistics"
        )

        print(
            "Chunks:",
            statistics[
                "total_chunks"
            ]
        )

        print(
            "Indexed Files:",
            statistics[
                "total_indexed_files"
            ]
        )

        print(
            "\nIndexed Files:"
        )

        for file_path in (
            rag.get_indexed_files()
        ):

            print(
                " -",
                file_path
            )

    # ============================================================
    # Interactive testing
    # ============================================================

    while rag.vector_database_exists():

        question = input(
            "\nAsk Question "
            "(type 'exit' to quit): "
        )

        if (
            question.strip().lower()
            == "exit"
        ):

            break

        try:

            print(
                "\nClassification:",
                rag.classify_query(
                    question
                )
            )

            prompt = (
                rag.generate_prompt(
                    question
                )
            )

            print(
                "\nPrompt generated successfully."
            )

            print(
                "Prompt characters:",
                len(prompt)
            )

        except Exception as e:

            print(
                "Error:",
                repr(e)
            )