from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class DbtCommand:
    argv: tuple[str,...]
    def shell_preview(self) -> str: return " ".join(self.argv)

class LocalDbtProjectAdapter:
    def __init__(self, project_dir: str | Path) -> None: self.project_dir=Path(project_dir)
    def project_metadata(self) -> dict[str,Any]:
        project_file=self.project_dir/"dbt_project.yml"; return {"project_dir":str(self.project_dir),"project_file":str(project_file),"exists":project_file.exists()}
    def load_manifest(self,path: str|Path|None=None) -> dict[str,Any]:
        manifest_path=Path(path) if path else self.project_dir/"target"/"manifest.json"
        if not manifest_path.exists(): raise FileNotFoundError(f"dbt manifest not found: {manifest_path}")
        return json.loads(manifest_path.read_text())
    @staticmethod
    def _nodes_by_type(manifest: dict[str,Any],resource_type: str) -> list[str]:
        nodes={**manifest.get("nodes",{}),**manifest.get("sources",{})}; return sorted(uid for uid,node in nodes.items() if node.get("resource_type")==resource_type)
    def list_models(self,m): return self._nodes_by_type(m,"model")
    def list_sources(self,m): return self._nodes_by_type(m,"source")
    def list_tests(self,m): return self._nodes_by_type(m,"test")
    def downstream(self,manifest: dict[str,Any],node_id: str) -> list[str]:
        child_map=manifest.get("child_map",{}); seen=set(); queue=list(child_map.get(node_id,[]))
        while queue:
            current=queue.pop(0)
            if current in seen: continue
            seen.add(current); queue.extend(child_map.get(current,[]))
        return sorted(seen)
    def upstream(self, manifest: dict[str,Any], node_id: str) -> list[str]:
        from agentic_data_platform.dbt.intelligence import get_upstream_nodes
        return get_upstream_nodes(manifest,node_id)
    def changed(self, previous: dict[str,Any], current: dict[str,Any]) -> list[str]:
        from agentic_data_platform.dbt.intelligence import get_changed_nodes
        return get_changed_nodes(previous,current)
    def build_command(self,selector=None): return self._command("build",selector)
    def _command(self,verb: str,selector: str|None=None) -> DbtCommand:
        argv=["dbt",verb,"--project-dir",str(self.project_dir)]
        if selector: argv += ["--select",selector]
        return DbtCommand(tuple(argv))
    def compile_command(self,selector=None): return self._command("compile",selector)
    def test_command(self,selector=None): return self._command("test",selector)
    def run_command(self,selector=None): return self._command("run",selector)
