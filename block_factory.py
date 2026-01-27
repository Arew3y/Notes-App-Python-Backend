import uuid
from typing import Dict, Any, Callable

# Imports
from note_schema import NoteBlock, CURRENT_BLOCK_VERSION
from logger_service import sys_log, LogSource, LogLevel


class BlockFactory:
    """
    A Factory registry for creating NoteBlock OBJECTS with specific data structures.
    """
    _creators: Dict[str, Callable[..., Dict[str, Any]]] = {}

    @classmethod
    def register(cls, block_type: str, creator_func: Callable[..., Dict[str, Any]]):
        """Register a new block type and its data generator function."""
        cls._creators[block_type] = creator_func

    @classmethod
    def create(cls, block_type: str, **kwargs) -> NoteBlock:
        """
        Constructs a NoteBlock Object with the correct internal data structure.
        """
        # 1. Get the specific data generator (The Blueprint)
        creator = cls._creators.get(block_type)

        content_data = {}
        if not creator:
            # Log Warning if type is unknown
            sys_log.log(
                LogSource.SYSTEM,
                LogLevel.WARNING,
                f"BlockFactory: Unknown block type '{block_type}'. Defaulting to empty data."
            )
        else:
            # 2. Generate the specific 'data' payload
            content_data = creator(**kwargs)

        # 3. Create the strictly typed Object
        new_block = NoteBlock(
            block_id=str(uuid.uuid4()),
            type=block_type,
            data=content_data,
            version=CURRENT_BLOCK_VERSION,
            tags=[],
            backlinks=[]
        )

        # Log Success (Debug level so it doesn't clutter INFO)
        sys_log.log(
            LogSource.SYSTEM,
            LogLevel.DEBUG,
            f"BlockFactory: Created '{block_type}' block",
            meta={"id": new_block.block_id}
        )

        return new_block


# ==========================================
# Define Block Blueprints (The Data Generators)
# ==========================================

def _create_text_block(content: str = "", fmt: str = "markdown") -> Dict[str, Any]:
    return {
        "content": content,
        "format": fmt
    }


def _create_todo_block(content: str = "", checked: bool = False) -> Dict[str, Any]:
    return {
        "content": content,
        "checked": checked
    }


def _create_code_block(code: str = "", language: str = "python") -> Dict[str, Any]:
    return {
        "code": code,
        "language": language,
        "output": ""
    }


def _create_image_block(src: str = "", caption: str = "") -> Dict[str, Any]:
    return {
        "src": src,
        "caption": caption,
        "alignment": "center"
    }


def _create_latex_block(formula: str = "") -> Dict[str, Any]:
    return {
        "formula": formula,
        "display_mode": True
    }


# ==========================================
# Register them
# ==========================================
BlockFactory.register("text", _create_text_block)
BlockFactory.register("todo", _create_todo_block)
BlockFactory.register("code", _create_code_block)
BlockFactory.register("image", _create_image_block)
BlockFactory.register("latex", _create_latex_block)