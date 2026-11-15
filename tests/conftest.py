import os

# Protect against Windows Sandbox OpenMP handle exception (0xc0000008) when loading native faiss DLLs.
# NumPy fallback vector store provides identical vector cosine search without DLL conflicts.
os.environ.setdefault("VICTOR_DISABLE_FAISS", "1")
