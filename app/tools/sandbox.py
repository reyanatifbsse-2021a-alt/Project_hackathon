"""
AegisRuntime - Tool Sandbox & Execution Registry
Ensures all protected actions go strictly through the sandboxed registry
with token verification. No secondary routes exist.
"""

from typing import Dict, Any, Optional
from app.tools.tool_implementations import (
    ProtectedTool,
    ExportDataTool,
    PrescribeMedicationTool,
    WireTransferTool,
    CloudStorageTool,
    DeleteResourceTool,
    ReadDataTool
)


class ToolRegistry:
    """Central registry of all executable tools in the system."""

    def __init__(self):
        self._tools: Dict[str, ProtectedTool] = {
            "export_data": ExportDataTool(),
            "prescribe_medication": PrescribeMedicationTool(),
            "wire_transfer": WireTransferTool(),
            "cloud_storage": CloudStorageTool(),
            "delete_resource": DeleteResourceTool(),
            "read_data": ReadDataTool(),
            "system_metrics": ReadDataTool()
        }

    def get_tool(self, tool_name: str) -> Optional[ProtectedTool]:
        return self._tools.get(tool_name)

    def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        token: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executes the tool in the protected sandbox.
        Protected tools physically raise SecurityViolationException if token is absent or invalid.
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return {
                "status": "ERROR",
                "tool": tool_name,
                "message": f"Tool '{tool_name}' is not recognized in the execution sandbox."
            }

        return tool.execute(parameters, token=token)
