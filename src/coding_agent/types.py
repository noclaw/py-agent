"""Core data types for the agent (Phase 2).

Port target: ``packages/agent/src/types.ts``.

Will define:
  * ``AgentMessage`` (persisted/in-context message: user / assistant / toolResult, with
    model + usage metadata) and a converter to pi-ai wire ``Message`` objects
    (the ``convertToLlm`` equivalent consumed by :class:`pi_py_sdk.model.PiModelClient`).
  * The agent event taxonomy emitted by the loop (agent_start, turn_start,
    message_start/update/end, tool_execution_start/update/end, turn_end, agent_end).
  * The ``Tool`` protocol (name/description/JSON-Schema parameters/execute), shared with
    :mod:`coding_agent.tools`.

Tool parameter schemas are defined as Pydantic models and exported as JSON Schema via
``model_json_schema()`` (the readable stand-in for Pi's TypeBox schemas).
"""

from __future__ import annotations
