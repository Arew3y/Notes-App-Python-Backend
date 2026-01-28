from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from typing import Dict, Any, Optional

# 1. Base Configuration (The Rosetta Stone)
class PyTauriModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,  # Converts snake_case -> camelCase
        populate_by_name=True,     # Allows Python to still use snake_case
        extra="forbid",            # Strict mode: rejects unknown fields
    )

# 2. Requests (Frontend -> Backend)
class OpenNoteRequest(PyTauriModel):
    note_id: str

class CreateBlockRequest(PyTauriModel):
    note_id: str
    block_type: str
    content_data: Dict[str, Any]

class UpdateBlockRequest(PyTauriModel):
    note_id: str
    block_id: str
    new_data: Dict[str, Any]

class DeleteBlockRequest(PyTauriModel):
    note_id: str
    block_id: str

class VaultConfig(PyTauriModel):
    path: str

# 3. Responses (Backend -> Frontend)
class OperationResponse(PyTauriModel):
    success: bool
    message: str = ""
    data: Optional[Dict[str, Any]] = None