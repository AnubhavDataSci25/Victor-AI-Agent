"""
Workspace resolution and project inspection for Victor's Coding Control.

Enforces strict path safety on Windows, shallow search across approved workspace roots,
automatic framework/language detection, and compact context construction.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from app.coding.models import (
    CompactProjectContext,
    ProjectMetadata,
    ProjectType,
)
from app.logging import get_logger

logger = get_logger("coding.workspace")

# Directories strictly ignored during tree walking or project searches
IGNORED_DIRS = {
    ".git",
    ".github",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "target",
    "bin",
    "obj",
    ".idea",
    ".vscode",
    "AppData",
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "$Recycle.Bin",
    "System Volume Information",
    ".cache",
    "Temp",
}


class WorkspaceResolutionError(Exception):
    """Raised when a workspace path cannot be resolved or is invalid."""


class WorkspaceSecurityError(Exception):
    """Raised when a path falls outside approved workspace roots."""


class WorkspaceResolver:
    """Resolves and validates workspace paths without guessing or scanning whole drives."""

    def __init__(self, approved_roots: list[str] | None = None) -> None:
        self.approved_roots = self._normalize_roots(approved_roots or [])

    @staticmethod
    def _normalize_roots(raw_roots: list[str]) -> list[Path]:
        normalized = []
        for r in raw_roots:
            try:
                p = Path(os.path.expanduser(r)).resolve()
                normalized.append(p)
            except Exception:
                continue
        return normalized

    def _is_path_under_approved_roots(self, candidate: Path) -> bool:
        if not self.approved_roots:
            return True
        candidate_lower = str(candidate).lower()
        for root in self.approved_roots:
            root_lower = str(root).lower().rstrip("\\/")
            if candidate_lower == root_lower or candidate_lower.startswith(root_lower + "\\") or candidate_lower.startswith(root_lower + "/"):
                return True
        return False

    def resolve_workspace(self, target: str) -> Path:
        """
        Resolve a path or bare project name into a validated workspace Path.

        Rules:
        - If target is a path (starts with drive letter, /, \\, or contains separators),
          validate it directly.
        - If target is a bare name, search ONLY approved workspace roots (depth <= 2).
        - Rejects paths outside approved roots.
        """
        if not target or not target.strip():
            raise WorkspaceResolutionError("Project path or name cannot be empty.")

        target = target.strip().strip("'\"")

        # Check if target is an explicit path
        is_explicit_path = (
            ":" in target
            or target.startswith(("\\", "/"))
            or "\\" in target
            or "/" in target
            or target in (".", "..")
        )

        if is_explicit_path:
            candidate = Path(os.path.expanduser(target)).resolve()
            if not candidate.exists():
                raise WorkspaceResolutionError(f"Workspace path does not exist: {candidate}")
            if not candidate.is_dir():
                raise WorkspaceResolutionError(f"Workspace path is not a directory: {candidate}")
            if not self._is_path_under_approved_roots(candidate):
                raise WorkspaceSecurityError(
                    f"Workspace path {candidate} is outside approved workspace locations: "
                    f"{[str(r) for r in self.approved_roots]}"
                )
            return candidate

        # Bare project name: perform shallow search only in approved roots
        matched_paths = self._find_project_by_name(target)
        if len(matched_paths) == 1:
            return matched_paths[0]
        elif len(matched_paths) > 1:
            paths_str = "\n".join(f"- {p}" for p in matched_paths[:5])
            raise WorkspaceResolutionError(
                f"Multiple projects found matching '{target}'. Please specify the exact path:\n{paths_str}"
            )
        else:
            raise WorkspaceResolutionError(
                f"Could not find project named '{target}' within approved workspace locations. "
                f"Please provide the full path (e.g., E:\\MyProject or C:\\Projects\\{target})."
            )

    def _find_project_by_name(self, name: str) -> list[Path]:
        """Search approved roots up to depth 2 for a directory matching `name`."""
        target_name = name.lower().strip()
        matches: list[Path] = []
        seen_resolved: set[str] = set()

        def _add_match(p: Path):
            try:
                resolved_key = str(p.resolve()).lower()
                if resolved_key not in seen_resolved:
                    seen_resolved.add(resolved_key)
                    matches.append(p)
            except Exception:
                pass

        for root in self.approved_roots:
            if not root.exists() or not root.is_dir():
                continue

            # Check if root itself matches
            if root.name.lower() == target_name:
                _add_match(root)
                continue

            try:
                # Level 1 scan
                with os.scandir(root) as it:
                    for entry in it:
                        try:
                            if not entry.is_dir(follow_symlinks=False):
                                continue
                            if entry.name in IGNORED_DIRS or entry.name.startswith("."):
                                continue

                            entry_path = Path(entry.path)
                            if entry.name.lower() == target_name:
                                _add_match(entry_path)
                                continue

                            # Level 2 scan
                            try:
                                with os.scandir(entry_path) as sub_it:
                                    for sub_entry in sub_it:
                                        if not sub_entry.is_dir(follow_symlinks=False):
                                            continue
                                        if sub_entry.name in IGNORED_DIRS or sub_entry.name.startswith("."):
                                            continue
                                        if sub_entry.name.lower() == target_name:
                                            _add_match(Path(sub_entry.path))
                            except (PermissionError, OSError):
                                continue

                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError) as exc:
                logger.debug(f"Skipping unreadable root {root}: {exc}")
                continue

        return matches


class ProjectInspector:
    """Inspects workspace structure, identifies framework/language, and builds compact context."""

    @staticmethod
    def detect_project_type(workspace: Path) -> ProjectMetadata:
        metadata = ProjectMetadata()

        # Check Python
        pyproject = workspace / "pyproject.toml"
        requirements = workspace / "requirements.txt"
        setup_py = workspace / "setup.py"
        pipfile = workspace / "Pipfile"
        manage_py = workspace / "manage.py"

        # Check Node / JS / TS
        package_json = workspace / "package.json"

        # Check Rust / Go / C# / Java
        cargo_toml = workspace / "Cargo.toml"
        go_mod = workspace / "go.mod"
        pom_xml = workspace / "pom.xml"

        csproj_files = list(workspace.glob("*.csproj")) if workspace.exists() else []

        if package_json.exists():
            metadata.project_type = ProjectType.NODE
            metadata.language = "javascript/typescript"
            metadata.config_files.append("package.json")
            try:
                import json
                data = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                metadata.dependencies = list(deps.keys())[:30]

                if "next" in deps:
                    metadata.framework = "Next.js"
                elif "react" in deps:
                    metadata.framework = "React"
                elif "vue" in deps:
                    metadata.framework = "Vue"
                elif "express" in deps:
                    metadata.framework = "Express"
                elif "fastify" in deps:
                    metadata.framework = "Fastify"

                if (workspace / "pnpm-lock.yaml").exists():
                    metadata.package_manager = "pnpm"
                elif (workspace / "yarn.lock").exists():
                    metadata.package_manager = "yarn"
                else:
                    metadata.package_manager = "npm"

                metadata.test_runner = "npm test"
            except Exception as e:
                logger.warning(f"Error reading package.json: {e}")

        elif pyproject.exists() or requirements.exists() or setup_py.exists() or pipfile.exists() or manage_py.exists():
            metadata.project_type = ProjectType.PYTHON
            metadata.language = "python"
            metadata.package_manager = "pip"
            metadata.test_runner = "pytest"

            req_content = ""
            if requirements.exists():
                metadata.config_files.append("requirements.txt")
                try:
                    req_content += requirements.read_text(encoding="utf-8", errors="replace").lower()
                except Exception:
                    pass

            if pyproject.exists():
                metadata.config_files.append("pyproject.toml")
                try:
                    req_content += pyproject.read_text(encoding="utf-8", errors="replace").lower()
                except Exception:
                    pass

            # Detect Framework
            if manage_py.exists() or "django" in req_content:
                metadata.framework = "Django"
                metadata.entry_points.append("manage.py")
            elif "fastapi" in req_content:
                metadata.framework = "FastAPI"
            elif "flask" in req_content:
                metadata.framework = "Flask"
            elif "streamlit" in req_content:
                metadata.framework = "Streamlit"

            # Detect Entry Points
            for candidate in ("main.py", "app.py", "run.py", "server.py", "index.py"):
                if (workspace / candidate).exists():
                    metadata.entry_points.append(candidate)

        elif cargo_toml.exists():
            metadata.project_type = ProjectType.RUST
            metadata.language = "rust"
            metadata.config_files.append("Cargo.toml")
            metadata.package_manager = "cargo"
            metadata.test_runner = "cargo test"

        elif go_mod.exists():
            metadata.project_type = ProjectType.GO
            metadata.language = "go"
            metadata.config_files.append("go.mod")
            metadata.package_manager = "go"
            metadata.test_runner = "go test"

        elif csproj_files or list(workspace.glob("*.sln")):
            metadata.project_type = ProjectType.CSHARP
            metadata.language = "csharp"
            metadata.config_files.extend([f.name for f in csproj_files[:3]])
            metadata.package_manager = "dotnet"
            metadata.test_runner = "dotnet test"

        elif pom_xml.exists() or (workspace / "build.gradle").exists():
            metadata.project_type = ProjectType.JAVA
            metadata.language = "java"
            metadata.config_files.append("pom.xml" if pom_xml.exists() else "build.gradle")
            metadata.package_manager = "mvn" if pom_xml.exists() else "gradle"

        return metadata

    @classmethod
    def build_compact_context(
        cls,
        workspace: Path,
        task_query: str = "",
        max_tree_entries: int = 50,
        max_file_preview_lines: int = 80,
    ) -> CompactProjectContext:
        """
        Builds a compact skeleton tree, summarizes configuration, and retrieves
        targeted relevant files without uploading the whole repository.
        """
        metadata = cls.detect_project_type(workspace)

        # 1. Build skeleton tree (depth 3, max entries)
        tree_lines: list[str] = []
        count = 0

        for root, dirs, files in os.walk(workspace):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]

            rel_root = Path(root).relative_to(workspace)
            depth = len(rel_root.parts)
            if depth >= 3:
                dirs.clear()
                continue

            indent = "  " * depth
            if rel_root != Path("."):
                tree_lines.append(f"{indent}{rel_root.name}/")
                count += 1

            for f in sorted(files):
                if count >= max_tree_entries:
                    tree_lines.append(f"{indent}  ... (remaining files omitted)")
                    dirs.clear()
                    break
                if not f.startswith("."):
                    tree_lines.append(f"{indent}  {f}")
                    count += 1

            if count >= max_tree_entries:
                break

        skeleton_tree = "\n".join(tree_lines) if tree_lines else "(empty directory)"

        # 2. Key config summaries (first 30 lines)
        key_file_summaries: dict[str, str] = {}
        for config_name in metadata.config_files[:3]:
            cfg_path = workspace / config_name
            if cfg_path.is_file():
                try:
                    lines = cfg_path.read_text(encoding="utf-8", errors="replace").splitlines()[:30]
                    key_file_summaries[config_name] = "\n".join(lines)
                except Exception:
                    pass

        # 3. Targeted relevant files
        relevant_files: list[dict[str, str]] = []
        task_terms = [t.lower() for t in re.findall(r"\w+", task_query) if len(t) > 2]

        candidate_files = []
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            rel_root = Path(root).relative_to(workspace)
            if len(rel_root.parts) >= 3:
                dirs.clear()
                continue
            for f in files:
                if f.endswith((".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".rs", ".go", ".cs")):
                    file_path = Path(root) / f
                    rel_path = str(file_path.relative_to(workspace))
                    candidate_files.append((rel_path, file_path))

        # Score candidate files based on entry points and task query
        scored_candidates = []
        for rel_path, file_path in candidate_files:
            score = 0
            rel_lower = rel_path.lower()
            # Entry point boost
            if rel_path in metadata.entry_points:
                score += 5
            # Query term match
            for term in task_terms:
                if term in rel_lower:
                    score += 4
            # Common primary files
            if any(rel_lower.endswith(k) for k in ("main.py", "app.py", "index.ts", "index.js", "router.py", "routes.py")):
                score += 2
            if score > 0:
                scored_candidates.append((score, rel_path, file_path))

        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        for _, rel_path, file_path in scored_candidates[:3]:
            try:
                content_lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()[:max_file_preview_lines]
                preview = "\n".join(content_lines)
                relevant_files.append({
                    "path": rel_path,
                    "content": preview,
                })
            except Exception:
                pass

        return CompactProjectContext(
            root_path=str(workspace),
            project_name=workspace.name,
            metadata=metadata,
            skeleton_tree=skeleton_tree,
            key_file_summaries=key_file_summaries,
            relevant_files=relevant_files,
        )
