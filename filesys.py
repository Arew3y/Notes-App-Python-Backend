import json
import ijson
import uuid
import os
import shutil
from datetime import datetime
from pathlib import Path

# Import the specific dataclasses and the DB class
from cache_db import FileIndex, NoteMetadata, DirectoryMetadata

# Initialize the DB
localdb = FileIndex()


# ==========================================
# Core Scanning & Sync Logic
# ==========================================

def initialize_vault_scan(root_dir: Path):
    """
    Full scan: Wipes the DB for this root and rebuilds it from scratch.
    Useful for initialization or hard resets.
    """
    root_dir = Path(root_dir)
    if not root_dir.exists():
        return

    # Optional: Clear existing entries for this root (if you track roots)
    # localdb.cursor.execute("DELETE FROM notes")
    # localdb.cursor.execute("DELETE FROM directories")

    _walk_and_populate(root_dir)


def quick_scan(root_dir: Path):
    """
    Smart Sync:
    1. Walks the filesystem to find new/modified files.
    2. Checks the DB to find 'ghost' files (entries that no longer exist on disk) and removes them.
    """
    root_dir = Path(root_dir)
    if not root_dir.exists():
        return

    # Track what we find on disk to verify against DB later
    found_note_ids = set()
    found_dir_paths = set()

    # 1. Walk disk and Upsert (Add/Update)
    for current_path, dirs, files in os.walk(root_dir):
        current_path_obj = Path(current_path)

        # Track Directory
        found_dir_paths.add(str(current_path_obj))

        # Register/Update Directory in DB
        # We skip the root folder itself if strictly needed, but usually it's fine
        if current_path_obj != root_dir:
            dir_meta = DirectoryMetadata(
                dir_path=current_path_obj,
                dir_name=current_path_obj.name,
                parent_path=current_path_obj.parent
            )
            localdb.add_directory(dir_meta)

        # Process Files
        for file_name in files:
            if file_name.endswith(".jnote"):
                file_path = current_path_obj / file_name
                try:
                    # We only read metadata to save IO
                    raw_meta = extract_note_metadata(file_path)
                    if not raw_meta: continue

                    n_id = raw_meta.get("note_id")
                    if n_id:
                        found_note_ids.add(n_id)

                        # Upsert Note into DB
                        note_obj = NoteMetadata(
                            note_id=n_id,
                            note_title=raw_meta.get("title", file_name),
                            note_version=str(raw_meta.get("version", "1.0")),
                            note_dir=current_path_obj
                        )
                        localdb.add_metadata(note_obj)
                except Exception:
                    continue

    # 2. Cleanup (Garbage Collection)
    # Check DB for items that were NOT found in the walk

    # Clean Notes
    all_db_notes = localdb.get_all_notes()  # You might want a lighter query just for IDs
    for note in all_db_notes:
        if note.note_id not in found_note_ids:
            localdb.delete_note(note.note_id)

    # Clean Directories
    # (Implementation requires a method to get all dirs from DB, assumed similar to get_all_notes)
    # localdb.cursor.execute("SELECT dir_path FROM directories")
    # all_db_dirs = [r[0] for r in localdb.cursor.fetchall()]
    # for d_path in all_db_dirs:
    #     if d_path not in found_dir_paths:
    #          _delete_directory_from_db_only(d_path)


def _walk_and_populate(root_dir: Path):
    """Helper for the full scan."""
    print(f"Starting Scan on: {root_dir}")
    for current_path, dirs, files in os.walk(root_dir):
        current_path_obj = Path(current_path)

        for dir_name in dirs:
            full_dir_path = current_path_obj / dir_name
            localdb.add_directory(DirectoryMetadata(
                dir_path=full_dir_path,
                dir_name=dir_name,
                parent_path=current_path_obj
            ))

        for file_name in files:
            if file_name.endswith(".jnote"):
                file_path = current_path_obj / file_name
                raw_meta = extract_note_metadata(file_path)
                if raw_meta:
                    localdb.add_metadata(NoteMetadata(
                        note_id=raw_meta.get("note_id", str(uuid.uuid4())),
                        note_title=raw_meta.get("title", file_name),
                        note_version=str(raw_meta.get("version", "1.0")),
                        note_dir=current_path_obj
                    ))


# ==========================================
# CRUD: Notes
# ==========================================

def create_new_note(base_dir: str, title: str = "Untitled Note"):
    # 1. Setup paths
    base_path = Path(base_dir)
    note_id = str(uuid.uuid4())
    # Filename is the ID to avoid issues with special characters in titles
    file_name = f"{note_id}.jnote"
    file_path = base_path / file_name

    # 2. Prepare the data structure
    timestamp = datetime.now().isoformat()
    note_data = {
        "metadata": {
            "title": title,
            "created_at": timestamp,
            "last_modified": timestamp,
            "version": 1.0,
            "note_id": note_id,
            "status": 0,  # 0 = Active
            "tags": []
        },
        "custom_fields": {},
        "blocks": [
            {
                "block_id": str(uuid.uuid4()),
                "type": "text",
                "version": 1.0,
                "backlinks": [],
                "tags": ["summary", "todo"],
                "data": {
                    "content": "This is the actual text content of my note.",
                    "format": "markdown"
                }
            },
            {
                "block_id": str(uuid.uuid4()),
                "type": "text",
                "version": 1.0,
                "backlinks": [],
                "tags": ["summary", "todo"],
                "data": {
                    "content": "This is the Second Block",
                    "format": "markdown"
                }
            }
        ]
    }

    # 3. Write to disk
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(note_data, f, indent=4)

        # 4. Update the DB immediately so UI stays in sync
        # We assume the directory already exists in DB, but we add the note
        new_note_meta = NoteMetadata(
            note_id=note_id,
            note_title=title,
            note_version="1.0",
            note_dir=base_path
        )
        localdb.add_metadata(new_note_meta)
        return {"success": True, "path": str(file_path), "note_id": note_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_note_metadata(note_id: str, new_title: str):
    """
    Updates the title in the JSON file AND the Database.
    Does NOT require opening the full file in the editor.
    """
    # 1. Get path from DB
    meta = localdb.get_metadata(note_id)
    if not meta:
        return {"success": False, "error": "Note not found in index."}

    file_path = meta.note_dir / f"{note_id}.jnote"

    if not file_path.exists():
        return {"success": False, "error": "File missing from disk."}

    # 2. Update JSON on disk
    try:
        with open(file_path, "r+", encoding="utf-8") as f:
            data = json.load(f)
            data['metadata']['title'] = new_title
            data['metadata']['last_modified'] = datetime.now().isoformat()

            f.seek(0)
            json.dump(data, f, indent=4)
            f.truncate()

        # 3. Update DB
        meta.note_title = new_title
        localdb.add_metadata(meta)  # upsert updates it

        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_note(note_id: str):
    # 1. Get info from DB
    meta = localdb.get_metadata(note_id)
    if not meta:
        return {"success": False, "error": "Note not found."}

    file_path = meta.note_dir / f"{note_id}.jnote"

    # 2. Delete from Disk
    try:
        if file_path.exists():
            os.remove(file_path)
    except Exception as e:
        return {"success": False, "error": f"Disk error: {str(e)}"}

    # 3. Delete from DB
    localdb.delete_note(note_id)
    return {"success": True}


# ==========================================
# CRUD: Directories
# ==========================================

def create_directory(parent_path: str, dir_name: str):
    target_path = Path(parent_path) / dir_name

    try:
        os.makedirs(target_path, exist_ok=False)

        # Update DB
        localdb.add_directory(DirectoryMetadata(
            dir_path=target_path,
            dir_name=dir_name,
            parent_path=Path(parent_path)
        ))
        return {"success": True, "path": str(target_path)}
    except FileExistsError:
        return {"success": False, "error": "Directory already exists."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_directory_name(old_path: str, new_name: str):
    old_p = Path(old_path)
    new_p = old_p.parent / new_name

    try:
        os.rename(old_p, new_p)
        # Using new DB method which handles deep recursion automatically
        localdb.update_directory(str(old_p), str(new_p), new_name)
        return {"success": True, "new_path": str(new_p)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def delete_directory(dir_path: str):
    path = Path(dir_path)
    try:
        if path.exists(): shutil.rmtree(path)
        localdb.delete_directory_recursive(str(path)) # Using new DB method
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==========================================
# Helpers
# ==========================================

def extract_note_metadata(file_path: Path):
    """Efficiently extracts metadata using ijson."""
    file_path = Path(file_path)
    metadata = {}
    try:
        with open(file_path, 'rb') as f:
            objects = ijson.items(f, 'metadata')
            for obj in objects:
                metadata = obj
                break
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    return metadata