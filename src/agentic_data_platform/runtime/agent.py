from __future__ import annotations
import json
from dataclasses import asdict
from typing import Any
from agentic_data_platform.models import ActorMode, Environment, ToolRequest, new_id
from agentic_data_platform.providers.base import Provider, ProviderRequest, ProviderResponse
from agentic_data_platform.runtime.context import ContextManager
from agentic_data_platform.runtime.store import RuntimeStore
from agentic_data_platform.tools.registry import ToolInvocation, ToolRegistry
from agentic_data_platform.tracing.store import TraceStore

class AgentLoopError(RuntimeError):
    pass

class AgentRuntime:
    def __init__(self, registry: ToolRegistry, store: RuntimeStore, traces: TraceStore, *,
                 context: ContextManager | None = None, max_steps: int = 12, repeated_tool_limit: int = 3) -> None:
        self.registry=registry; self.store=store; self.traces=traces
        self.context=context or ContextManager(); self.max_steps=max_steps; self.repeated_tool_limit=repeated_tool_limit
    def _tool_specs(self) -> list[dict[str, Any]]:
        return [{"name":i.name,"description":i.description,"input_schema":i.input_schema or {"type":"object"},"risk":i.risk.value}
                for i in self.registry.definitions() if i.enabled]
    def run(self, session_id: str, user_message: str, provider: Provider, model: str, *,
            actor_mode: ActorMode=ActorMode.ANALYST, environment: Environment=Environment.DEV,
            approved_tools: set[str] | None=None) -> dict[str, Any]:
        if self.store.get_session(session_id) is None: raise KeyError(f"session not found: {session_id}")
        approved_tools=approved_tools or set(); self.store.add_message(session_id,"user",user_message)
        trace_id=new_id("trace")
        root=self.traces.start("session","agent.run",trace_id=trace_id,session_id=session_id,
                               payload={"provider":provider.name,"model":model,"actor_mode":actor_mode.value,"environment":environment.value})
        signatures: dict[str,int]={}
        try:
            for step in range(1,self.max_steps+1):
                stored=self.store.messages(session_id)
                messages=[{"role":m["role"],"content":m["content"],**m["metadata"]} for m in stored]
                compacted,meta=self.context.compact(messages)
                self.store.add_context_snapshot(session_id,self.context.count_messages(compacted),meta)
                ge=self.traces.start("generation",f"{provider.name}:{model}",trace_id=trace_id,session_id=session_id,parent_id=root,
                                     payload={"step":step,"context":meta})
                response: ProviderResponse=provider.generate(ProviderRequest(model=model,messages=compacted,tools=self._tool_specs(),
                                                                            metadata={"session_id":session_id,"step":step}))
                gid=self.store.add_generation(session_id,provider.name,model,response.finish_reason,asdict(response.usage))
                self.traces.finish(ge,"SUCCESS",{"finish_reason":response.finish_reason,"usage":asdict(response.usage),
                                                "tool_call_count":len(response.tool_calls)})
                if response.content: self.store.add_message(session_id,"assistant",response.content)
                if not response.tool_calls:
                    self.traces.finish(root,"SUCCESS",{"steps":step})
                    return {"session_id":session_id,"trace_id":trace_id,"response":response.content,
                            "steps":step,"finish_reason":response.finish_reason}
                for call in response.tool_calls:
                    definition=self.registry.describe(call.name)
                    signature=f"{call.name}:{json.dumps(call.args,sort_keys=True,default=str)}"
                    signatures[signature]=signatures.get(signature,0)+1
                    if signatures[signature] > self.repeated_tool_limit:
                        raise AgentLoopError(f"repeated tool loop detected: {call.name}")
                    te=self.traces.start("tool",call.name,trace_id=trace_id,session_id=session_id,parent_id=ge,
                                         payload={"args":call.args,"risk":definition.risk.value})
                    cid=self.store.start_tool_call(session_id,gid,call.name,call.args,call.call_id)
                    req=ToolRequest(tool=call.name,operation=call.name,environment=environment,risk=definition.risk,args=dict(call.args))
                    try:
                        result=self.registry.invoke(ToolInvocation(req,run_id=session_id,approved=call.name in approved_tools,
                                                                  actor_mode=actor_mode))
                        status="SUCCESS"
                    except Exception as exc:
                        result={"error":type(exc).__name__,"message":str(exc)}
                        status="DENIED" if isinstance(exc,PermissionError) else "ERROR"
                    self.store.finish_tool_call(cid,result,status); self.traces.finish(te,status,{"result":result})
                    self.store.add_message(session_id,"tool",json.dumps(result,default=str),
                                           {"tool_call_id":call.call_id,"name":call.name,"status":status})
            raise AgentLoopError(f"maximum agent steps exceeded: {self.max_steps}")
        except Exception as exc:
            self.traces.finish(root,"ERROR",{"error":type(exc).__name__,"message":str(exc)})
            raise
