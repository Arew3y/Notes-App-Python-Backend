import json
import ijson
import os
import shutil
import time
from typing import Union, Callable, Optional, Dict, Any
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Imports from project modules
from cache_db import FileIndex, NoteMetadata, DirectoryMetadata
from note_schema import JNote
from logger_service import sys_log, LogSource, LogLevel

# Initialize the DB
localdb = FileIndex()


# ==========================================
# Placeholder for Active State Notification
# ==========================================
# This callback allows the Watcher to poke ActiveState when things change.
_on_file_change_callback: Optional[Callable[[str, float], None]] = None

def register_change_callback(func: Callable[[str, float], None]):
    """
    Called by main.py to hook up the ActiveManager.
    """
    global _on_file_change_callback
    _on_file_change_callback = func


# ==========================================
# Vault Watcher
# ==========================================

class VaultEventHandler(FileSystemEventHandler):
    """
    Handles all file system events and updates the CacheDB accordingly.
    This acts as the ONLY writer to the DB for structure changes.
    """

    @staticmethod
    def _get_note_meta(file_path: str) -> Optional[Dict]:
        """Helper to extract metadata efficiently."""
        return VaultWatcher.extract_note_metadata(Path(file_path))

    @staticmethod
    def _notify_active_state(path: Path, mtime: float = None):
        """
        Helper to safely fire the callback for ANY path (Note or Directory).
        """
        # 1. Capture global variable locally (Fixes "None is not callable" & Thread safety)
        callback = _on_file_change_callback

        if callback is None:
            return

        try:
            # If mtime is not provided, fetch it
            if mtime is None:
                if path.exists():
                    mtime = os.path.getmtime(path)
                else:
                    mtime = time.time()  # Timestamp for 'now' if deleted

            callback(str(path.resolve()), mtime)
        except Exception as e:
            # Don't crash the watcher if the callback fails
            sys_log.log(LogSource.SYSTEM, LogLevel.WARNING, "Failed to notify ActiveState", meta={"error": str(e)})

    # --- NEW HELPER METHOD ---
    def _process_note_file(self, file_path: Path):
        """
        Common logic to Register/Update a note in DB and Notify ActiveState.
        """
        # 1. Update DB
        meta_dict = self._get_note_meta(str(file_path))
        if meta_dict:
            db_meta = NoteMetadata(
                note_id=meta_dict.get("note_id"),
                note_title=meta_dict.get("title", file_path.stem),
                note_version=str(meta_dict.get("version", "1.0")),
                note_dir=file_path.parent
            )
            localdb.add_metadata(db_meta)

        # 2. Notify ActiveState (Note Change)
        self._notify_active_state(file_path)

    def on_created(self, event):
        path = Path(event.src_path)
        sys_log.log(LogSource.SYSTEM, LogLevel.DEBUG, f"Watcher: Created {path.name}")

        if event.is_directory:
            # Register Directory
            localdb.add_directory(DirectoryMetadata(
                dir_path=path,
                dir_name=path.name,
                parent_path=path.parent
            ))
            # NOTIFY TREE REFRESH
            self._notify_active_state(path)

        elif path.suffix == ".jnote":
            # Register Note
            self._process_note_file(path)

    def on_deleted(self, event):
        path = Path(event.src_path)
        sys_log.log(LogSource.SYSTEM, LogLevel.DEBUG, f"Watcher: Deleted {path.name}")

        if event.is_directory:
            localdb.delete_directory_recursive(str(path))
            # NOTIFY TREE REFRESH
            self._notify_active_state(path)

        elif path.suffix == ".jnote":
            # Option A: Since filename is UUID.jnote, stem is the ID.
            note_id = path.stem
            localdb.delete_note(note_id)
            sys_log.log(LogSource.SYSTEM, LogLevel.INFO, f"Watcher: Removed ghost entry for {note_id}")

            # NOTIFY ACTIVE NOTE (To close tab or show error)
            self._notify_active_state(path)

    def on_modified(self, event):
        if event.is_directory: return

        path = Path(event.src_path)
        if path.suffix == ".jnote":
            # Use the helper with the source path
            self._process_note_file(path)

    def on_moved(self, event):
        src_path = Path(event.src_path)
        dest_path = Path(event.dest_path)
        sys_log.log(LogSource.SYSTEM, LogLevel.INFO, f"Watcher: Moved {src_path.name} -> {dest_path.name}")

        if event.is_directory:
            localdb.update_directory(str(src_path), str(dest_path), dest_path.name)
            # NOTIFY TREE REFRESH (Target is the new location)
            self._notify_active_state(dest_path)

        elif dest_path.suffix == ".jnote":
            self._process_note_file(dest_path)


class VaultWatcher:
    """
    Singleton service that manages the file system observer.
    """

    def __init__(self, root_path: Union[str, Path]):
        self.root_path = Path(root_path)
        self.observer = Observer()
        self.handler = VaultEventHandler()

    def start(self):
        if not self.root_path.exists():
            sys_log.log(LogSource.SYSTEM, LogLevel.ERROR, f"Vault path missing: {self.root_path}")
            return

        # 1. Initial Full Scan (Populate DB)
        self.initialize_vault_scan()

        # 2. Start Watching
        self.observer.schedule(self.handler, str(self.root_path), recursive=True)
        self.observer.start()
        sys_log.log(LogSource.SYSTEM, LogLevel.INFO, f"VaultWatcher started on: {self.root_path}")

    def stop(self):
        self.observer.stop()
        self.observer.join()
        sys_log.log(LogSource.SYSTEM, LogLevel.INFO, "VaultWatcher stopped.")

    def initialize_vault_scan(self):
        """
        Wipes (optionally) and rebuilds the DB index from disk.
        """
        sys_log.log(LogSource.SYSTEM, LogLevel.INFO, "Starting Initial Vault Scan...")
        # localdb.cursor.execute("DELETE FROM notes") # Optional: Fresh start

        for current_path, dirs, files in os.walk(self.root_path):
            current_path_obj = Path(current_path)

            # Add Directories
            for dir_name in dirs:
                localdb.add_directory(DirectoryMetadata(
                    dir_path=current_path_obj / dir_name,
                    dir_name=dir_name,
                    parent_path=current_path_obj
                ))

            # Add Notes
            for file_name in files:
                if file_name.endswith(".jnote"):
                    file_path = current_path_obj / file_name
                    meta = self.extract_note_metadata(file_path)
                    if meta:
                        localdb.add_metadata(NoteMetadata(
                            note_id=meta.get("note_id"),
                            note_title=meta.get("title", file_name),
                            note_version=str(meta.get("version", "1.0")),
                            note_dir=current_path_obj
                        ))

        sys_log.log(LogSource.SYSTEM, LogLevel.INFO, "Vault Scan Complete.")

    @staticmethod
    def extract_note_metadata(file_path: Path) -> Dict[str, Any]:
        """
        Efficiently reads just the 'metadata' key from the JSON using ijson.
        """
        try:
            with open(file_path, 'rb') as f:
                # ijson.items returns a generator. We take the first 'metadata' object found.
                objects = ijson.items(f, 'metadata')
                for obj in objects:
                    return obj
        except Exception as e:
            sys_log.log(LogSource.SYSTEM, LogLevel.ERROR, f"Metadata extraction failed: {file_path.name}",
                        meta={"error": str(e)})
        return {}


# ==========================================
# CRUD Operations (Filesystem Only)
# ==========================================

def create_new_note(base_dir: str, title: str = "Untitled Note") -> Dict[str, Any]:
    """
    Creates a JNote object, saves it to disk.
    Watcher will handle the DB update.
    """
    try:
        # 1. Create Object using Schema
        new_note = JNote.create_new(title=title)
        note_id = new_note.metadata.note_id

        # 2. Determine Path
        file_path = Path(base_dir) / f"{note_id}.jnote"

        # 3. Save to Disk
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(new_note.to_dict(), f, indent=4)

        sys_log.log(LogSource.SYSTEM, LogLevel.INFO, f"Created new note: {title}", meta={"id": note_id})

        return {
            "success": True,
            "note_id": note_id,
            "path": str(file_path),
            # Return timestamp just in case caller needs it immediately
            "mtime": os.path.getmtime(file_path)
        }

    except Exception as e:
        sys_log.log(LogSource.SYSTEM, LogLevel.ERROR, "Create note failed", meta={"error": str(e)})
        return {"success": False, "error": str(e)}


def update_note(note: JNote) -> Dict[str, Any]:
    """
    Overwrites the file on disk with the provided JNote object.
    RETURNS timestamp for Echo Suppression.
    """
    try:
        note_id = note.metadata.note_id

        # 1. Find Path via DB
        meta = localdb.get_metadata(note_id)
        if not meta:
            return {"success": False, "error": f"Note {note_id} not found in index."}

        file_path = meta.note_dir / f"{note_id}.jnote"

        # 2. Update Timestamp in Object
        note.metadata.update_timestamp()

        # 3. Write to Disk
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(note.to_dict(), f, indent=4)

        # 4. Get Echo Timestamp
        # This is the magic number needed by ActiveNote to ignore the watchdog event
        mtime = os.path.getmtime(file_path)

        sys_log.log(LogSource.SYSTEM, LogLevel.INFO, f"Updated note {note_id}")

        return {"success": True, "mtime": mtime}

    except Exception as e:
        sys_log.log(LogSource.SYSTEM, LogLevel.ERROR, "Update note failed", meta={"error": str(e)})
        return {"success": False, "error": str(e)}


def delete_note(note_id: str) -> Dict[str, Any]:
    """
    Deletes the file. Watcher handles DB cleanup.
    """
    try:
        meta = localdb.get_metadata(note_id)
        if not meta:
            return {"success": False, "error": "Note not found."}

        file_path = meta.note_dir / f"{note_id}.jnote"

        if file_path.exists():
            os.remove(file_path)
            sys_log.log(LogSource.SYSTEM, LogLevel.INFO, f"Deleted note file: {note_id}")
            return {"success": True}
        else:
            return {"success": False, "error": "File already missing."}

    except Exception as e:
        sys_log.log(LogSource.SYSTEM, LogLevel.ERROR, "Delete note failed", meta={"error": str(e)})
        return {"success": False, "error": str(e)}


# ==========================================
# Directory CRUD (Filesystem Only)
# ==========================================

def create_directory(parent_path: str, dir_name: str) -> Dict[str, Any]:
    target_path = Path(parent_path) / dir_name
    try:
        os.makedirs(target_path, exist_ok=False)
        sys_log.log(LogSource.SYSTEM, LogLevel.INFO, f"Created directory: {dir_name}")
        return {"success": True, "path": str(target_path)}
    except Exception as e:
        sys_log.log(LogSource.SYSTEM, LogLevel.ERROR, "Create directory failed", meta={"error": str(e)})
        return {"success": False, "error": str(e)}


def update_directory_name(old_path: str, new_name: str) -> Dict[str, Any]:
    old_p = Path(old_path)
    new_p = old_p.parent / new_name
    try:
        os.rename(old_p, new_p)
        sys_log.log(LogSource.SYSTEM, LogLevel.INFO, f"Renamed directory: {old_p.name} -> {new_name}")
        return {"success": True, "new_path": str(new_p)}
    except Exception as e:
        sys_log.log(LogSource.SYSTEM, LogLevel.ERROR, "Rename directory failed", meta={"error": str(e)})
        return {"success": False, "error": str(e)}


def delete_directory(dir_path: str) -> Dict[str, Any]:
    path = Path(dir_path)
    try:
        if path.exists():
            shutil.rmtree(path)
            sys_log.log(LogSource.SYSTEM, LogLevel.INFO, f"Deleted directory: {path.name}")
            return {"success": True}
        return {"success": False, "error": "Path not found"}
    except Exception as e:
        sys_log.log(LogSource.SYSTEM, LogLevel.ERROR, "Delete directory failed", meta={"error": str(e)})
        return {"success": False, "error": str(e)}