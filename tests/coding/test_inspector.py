"""
Tests for ProjectInspector framework and language detection.
"""

from pathlib import Path
from app.coding.models import ProjectType
from app.coding.workspace import ProjectInspector


def test_detect_python_fastapi_project(tmp_path: Path):
    # Setup mock FastAPI project
    (tmp_path / "requirements.txt").write_text("fastapi>=0.100.0\nuvicorn\npydantic", encoding="utf-8")
    (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()", encoding="utf-8")

    meta = ProjectInspector.detect_project_type(tmp_path)
    assert meta.project_type == ProjectType.PYTHON
    assert meta.framework == "FastAPI"
    assert "main.py" in meta.entry_points
    assert "requirements.txt" in meta.config_files


def test_detect_node_react_project(tmp_path: Path):
    package_json = """{
      "name": "my-react-app",
      "dependencies": {
        "react": "^18.2.0",
        "react-dom": "^18.2.0"
      },
      "devDependencies": {
        "vite": "^4.0.0"
      }
    }"""
    (tmp_path / "package.json").write_text(package_json, encoding="utf-8")

    meta = ProjectInspector.detect_project_type(tmp_path)
    assert meta.project_type == ProjectType.NODE
    assert meta.framework == "React"
    assert meta.package_manager == "npm"


def test_build_compact_context(tmp_path: Path):
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\nrequests", encoding="utf-8")
    sub = tmp_path / "utils"
    sub.mkdir()
    (sub / "helper.py").write_text("def help(): pass", encoding="utf-8")

    ctx = ProjectInspector.build_compact_context(tmp_path, task_query="call helper")
    assert ctx.project_name == tmp_path.name
    assert "main.py" in ctx.skeleton_tree
    assert "helper.py" in ctx.skeleton_tree
    assert len(ctx.relevant_files) >= 1
