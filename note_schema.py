import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

# Import your Logger
from logger_service import sys_log, LogSource, LogLevel

# ==========================================
# Global Configuration (The Single Source of Truth)
# ==========================================
# Change these when you migrate your file format
CURRENT_BLOCK_VERSION = "1.0"
CURRENT_NOTE_VERSION = "1.0"


# ==========================================
# 1. The Block Schema
# ==========================================

@dataclass
class NoteBlock:
    """
    Represents a single content block (text, image, code, etc.).
    """
    block_id: str
    type: str
    data: Dict[str, Any]
    version: str = CURRENT_BLOCK_VERSION
    tags: List[str] = field(default_factory=list)
    backlinks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "NoteBlock":
        return NoteBlock(
            block_id=data.get("block_id", str(uuid.uuid4())),
            type=data.get("type", "text"),
            data=data.get("data", {}),
            version=data.get("version", CURRENT_BLOCK_VERSION),
            tags=data.get("tags", []),
            backlinks=data.get("backlinks", [])
        )


# ==========================================
# 2. The Metadata Schema
# ==========================================

@dataclass
class NoteMetadata:
    """
    Header information for the note.
    Matches your 'barebones.jnote' exactly.
    """
    note_id: str
    title: str
    created_at: str  # ISO 8601 String
    last_modified: str  # ISO 8601 String
    version: str = CURRENT_NOTE_VERSION
    status: int = 0  # 0 = Active, 1 = Archived, etc.
    tags: List[str] = field(default_factory=list)

    def update_timestamp(self):
        # FIX: Use strftime to ensure valid Z format without double offsets
        self.last_modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "NoteMetadata":
        # Safe extraction with defaults
        # FIX: Correct default timestamp format
        default_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        return NoteMetadata(
            note_id=data.get("note_id", str(uuid.uuid4())),
            title=data.get("title", "Untitled Note"),
            created_at=data.get("created_at", default_time),
            last_modified=data.get("last_modified", default_time),
            version=data.get("version", CURRENT_NOTE_VERSION),
            status=data.get("status", 0),
            tags=data.get("tags", [])
        )


# ==========================================
# 3. The Root Note Object (The JNote)
# ==========================================

@dataclass
class JNote:
    """
    The master object representing a full .jnote file.
    """
    metadata: NoteMetadata
    blocks: List[NoteBlock] = field(default_factory=list)
    custom_fields: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the full object tree back to the JSON structure
        required for saving to disk.
        """
        return {
            "metadata": self.metadata.to_dict(),
            "custom_fields": self.custom_fields,
            "blocks": [b.to_dict() for b in self.blocks]
        }

    @staticmethod
    def from_dict(data: Dict[str, Any], filepath: str = "Unknown") -> Optional["JNote"]:
        """
        Parses raw JSON data into a strictly typed JNote object.
        Returns None if critical data is missing.
        """
        try:
            # 1. Validate Metadata presence
            if "metadata" not in data:
                sys_log.log(LogSource.SYSTEM, LogLevel.ERROR, "Invalid JNote: Missing metadata",
                            meta={"path": filepath})
                return None

            # 2. Build Components
            meta_obj = NoteMetadata.from_dict(data["metadata"])

            blocks_list = []
            if "blocks" in data and isinstance(data["blocks"], list):
                for b_data in data["blocks"]:
                    blocks_list.append(NoteBlock.from_dict(b_data))

            return JNote(
                metadata=meta_obj,
                blocks=blocks_list,
                custom_fields=data.get("custom_fields", {})
            )

        except Exception as e:
            sys_log.log(LogSource.SYSTEM, LogLevel.ERROR, "Failed to parse JNote",
                        meta={"error": str(e), "path": filepath})
            return None

    # ==========================
    # Factory Methods (Creation)
    # ==========================

    @staticmethod
    def create_new(title: str = "Untitled Note") -> "JNote":
        """
        Creates a fresh, empty note with a valid ID and timestamps.
        (This replaces your old manual dictionary creation)
        """
        # FIX: consistent timestamp format
        now_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        new_id = str(uuid.uuid4())

        meta = NoteMetadata(
            note_id=new_id,
            title=title,
            created_at=now_str,
            last_modified=now_str,
            version=CURRENT_NOTE_VERSION,
            status=0,
            tags=[]
        )

        return JNote(metadata=meta)