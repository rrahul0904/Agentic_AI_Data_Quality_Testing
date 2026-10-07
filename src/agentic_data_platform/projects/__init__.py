"""Project-source adapters for ADE runtimes."""

from .sources import MaterializedProject, ProjectSourceError, materialize_git_project, resolve_hosted_project

__all__ = [
    "MaterializedProject",
    "ProjectSourceError",
    "materialize_git_project",
    "resolve_hosted_project",
]
