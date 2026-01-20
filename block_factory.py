import uuid
from typing import Dict, Any, Callable

class BlockFactory:
    """
    A Factory registry for creating different types of Note Blocks.
    """
    _creators: Dict[str, Callable[..., Dict[str, Any]]] = {}

    @classmethod
    def register(cls, block_type: str, creator_func: Callable[..., Dict[str, Any]]):
        """Register a new block type and its data generator function."""
        cls._creators[block_type] = creator_func

    @classmethod
    def create(cls, block_type: str, **kwargs) -> Dict[str, Any]:
        """
        Constructs a full block dictionary with the standard skeleton
        and type-specific data.
        """
        # 1. Standard Skeleton (Common to all blocks)
        block = {
            "block_id": str(uuid.uuid4()),
            "type": block_type,
            "version": 1.0,
            "backlinks": [],
            "tags": [],
            "data": {}
        }

        # 2. Get the specific data generator
        creator = cls._creators.get(block_type)

        if not creator:
            # Fallback: Create a generic block or raise an error
            print(f"[Warning] Unknown block type '{block_type}'. Defaulting to empty dict.")
            block["data"] = {}
        else:
            # 3. Inject specific data (passing any extra arguments needed)
            block["data"] = creator(**kwargs)

        return block

# ==========================================
# Define Block Schemas (The "Blueprints")
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

# ==========================================
# Register them
# ==========================================
BlockFactory.register("text", _create_text_block)
BlockFactory.register("todo", _create_todo_block)
BlockFactory.register("code", _create_code_block)
BlockFactory.register("image", _create_image_block)