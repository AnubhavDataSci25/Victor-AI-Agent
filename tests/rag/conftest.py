import os

# Ensure safe sandbox execution and fast deterministic offline testing for RAG unit tests
os.environ["VICTOR_DISABLE_FAISS"] = "1"
os.environ["VICTOR_FAST_EMBEDDING"] = "1"
