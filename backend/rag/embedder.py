#Convert chunks into embeddings   # backend/rag/embedder.py

from typing import List, Dict
from sentence_transformers import SentenceTransformer


class CodeEmbedder:
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        """
        Initialize the embedding model.
        """
        print("Loading embedding model...")
        try:
            self.model = SentenceTransformer(model_name, local_files_only=True)
        except Exception:
            self.model = SentenceTransformer(model_name, local_files_only=False)
        print("Embedding model loaded successfully.")

    def embed_chunks(self, chunks: List[Dict]) -> List[Dict]:
        """
        Generate embeddings for each chunk.

        Returns the same chunk dictionary with an added 'embedding' key.
        """

        texts = [chunk["content"] for chunk in chunks]

        embeddings = self.model.encode(
            texts,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True
        )

        embedded_chunks = []

        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding
            embedded_chunks.append(chunk)

        return embedded_chunks


if __name__ == "__main__":

    from loader import ProjectLoader
    from chunker import CodeChunker

    loader = ProjectLoader("../")
    documents = loader.load()

    chunker = CodeChunker()
    chunks = chunker.chunk_documents(documents)

    embedder = CodeEmbedder()

    embedded_chunks = embedder.embed_chunks(chunks)

    print("\nTotal Embedded Chunks:", len(embedded_chunks))

    print("\nExample:\n")

    sample = embedded_chunks[0]

    print("Chunk ID :", sample["chunk_id"])
    print("File     :", sample["name"])
    print("Vector Size :", len(sample["embedding"]))