import os
import json
import time
import threading
from block_factory import BlockFactory
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Import your existing DB instance
# We import localdb to query paths, avoiding a second DB connection if possible.
from filesys import localdb, initialize_vault_scan


# ==========================================
# 1. File Watcher Event Handler
# ==========================================
class NoteFileEventHandler(FileSystemEventHandler):
    """
    Listens for file system events.
    It filters events to ensure we only react to the specific note file we are watching.
    """

    def __init__(self, active_note_instance):
        self.note = active_note_instance

    def on_modified(self, event):
        # Watchdog returns paths as strings.
        # We normalize paths to ensure cross-platform compatibility (Windows vs Unix seps).
        event_path = os.path.normpath(event.src_path)
        watched_path = os.path.normpath(str(self.note.file_path))

        if event_path == watched_path:
            self.note.handle_external_modification()


# ==========================================
# 2. The Active Note Class
# ==========================================
class ActiveNote:
    """
    Represents a single open note in memory.
    Handles loading, auto-saving, and syncing with external file changes.
    """

    def __init__(self, note_id: str):
        self.note_id = note_id

        # 1. Resolve Path using your Cache DB
        # We fetch metadata to find the directory, then append {id}.jnote
        meta = localdb.get_metadata(note_id)
        if not meta:
            raise ValueError(f"Note ID {note_id} not found in Cache DB.")

        # Construct absolute path: directory from DB + filename pattern
        self.file_path = meta.note_dir / f"{note_id}.jnote"

        # 2. In-Memory Data Storage
        # We store the FULL JSON structure (metadata + blocks) to avoid losing data
        self.full_note_data: Dict[str, Any] = {}
        self.blocks: List[Dict[str, Any]] = []  # Shortcut reference to full_note_data['blocks']

        # 3. Threading & State Control
        self._lock = threading.Lock()  # Prevents read/write collisions
        self._save_timer: Optional[threading.Timer] = None  # For debouncing
        self.is_dirty = False  # Has memory changed since last save?
        self._ignore_next_watch_event = False  # Loop prevention flag

        # 4. Initial Load
        self._load_from_disk()

        # 5. Start Watchdog
        # We watch the parent directory because Watchdog cannot watch single files on all OSs easily
        self._observer = Observer()
        self._observer.schedule(
            NoteFileEventHandler(self),
            path=str(self.file_path.parent),
            recursive=False
        )
        self._observer.start()
        print(f"[ActiveNote] Started watching: {self.file_path.name}")

    def _load_from_disk(self):
        """
        Reads the .jnote file.
        Updates self.full_note_data and self.blocks.
        """
        with self._lock:
            if not self.file_path.exists():
                print(f"[Error] File missing: {self.file_path}")
                return

            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    self.full_note_data = json.load(f)

                    # Ensure 'blocks' exists
                    if "blocks" not in self.full_note_data:
                        self.full_note_data["blocks"] = []

                    # Create a reference for easy access
                    self.blocks = self.full_note_data["blocks"]

                print(f"[ActiveNote] Loaded {len(self.blocks)} blocks.")
            except json.JSONDecodeError:
                print(f"[Error] Corrupted JSON in {self.file_path}")

    def handle_external_modification(self):
        """
        Called when the file changes on disk (e.g. VS Code edit).
        """
        if self._ignore_next_watch_event:
            # We caused this change via auto-save. Ignore it.
            self._ignore_next_watch_event = False
            return

        print(f"[ActiveNote] External change detected! Reloading memory...")
        self._load_from_disk()

        # TODO: EMIT SIGNAL TO FRONTEND HERE
        # e.g., window.emit("note_reloaded", self.blocks)

    # ==========================
    # Block Operations (CRUD)
    # ==========================

    def update_block(self, block_id: str, new_content_data: Any):
        """
        Updates the 'data' field of a specific block.
        Expected new_content_data: dict, e.g. {"content": "New Text", "format": "markdown"}
        """
        with self._lock:
            found = False
            for block in self.blocks:
                if block.get("block_id") == block_id:
                    # Update data
                    block["data"] = new_content_data

                    found = True
                    break

            if not found:
                print(f"[Warning] Block {block_id} not found.")
                return

            self.is_dirty = True
            # Update root metadata timestamp
            if "metadata" in self.full_note_data:
                self.full_note_data["metadata"]["last_modified"] = time.strftime('%Y-%m-%dT%H:%M:%S')

        # Schedule a save (Debounce)
        self._schedule_save()

    def add_block(self, block_type: str = "text", prev_block_id: str = None, **kwargs):
        """
        Adds a new block using the Factory.
        Accepts **kwargs to pass initial data to specific block types (e.g. language="rust").
        If prev_block_id is provided, inserts AFTER that block.
        Otherwise, appends to end.
        """
        with self._lock:
            # BLOCK FACTORY
            new_block = BlockFactory.create(block_type, **kwargs)

            if prev_block_id:
                # Find index and insert after
                index = -1
                for i, b in enumerate(self.blocks):
                    if b["block_id"] == prev_block_id:
                        index = i
                        break
                if index != -1:
                    self.blocks.insert(index + 1, new_block)
                else:
                    self.blocks.append(new_block)
            else:
                self.blocks.append(new_block)

            self.is_dirty = True

        self._schedule_save()
        print(f"[ActiveNote] Added '{block_type}' block: {new_block['block_id']}")
        return new_block

    def delete_block(self, block_id: str):
        with self._lock:
            initial_len = len(self.blocks)
            self.blocks = [b for b in self.blocks if b.get("block_id") != block_id]

            # Re-link the reference in full_note_data (important!)
            self.full_note_data["blocks"] = self.blocks

            if len(self.blocks) < initial_len:
                self.is_dirty = True
                self._schedule_save()

    # ==========================
    # Auto-Save Logic
    # ==========================

    def _schedule_save(self):
        """
        Resets the timer. Only saves if user stops typing for 2.0 seconds.
        """
        if self._save_timer:
            self._save_timer.cancel()

        self._save_timer = threading.Timer(2.0, self._save_to_disk)
        self._save_timer.start()

    def _save_to_disk(self):
        """
        Writes self.full_note_data to disk.
        """
        with self._lock:
            if not self.is_dirty:
                return

            print(f"[ActiveNote] Auto-saving {self.note_id}...")

            # 1. Set Flag to ignore the upcoming Watchdog event
            self._ignore_next_watch_event = True

            try:
                with open(self.file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.full_note_data, f, indent=4)

                self.is_dirty = False
                print(f"[ActiveNote] Saved.")
            except Exception as e:
                print(f"[Error] Save failed: {e}")
                self._ignore_next_watch_event = False

    def close(self):
        """
        Cleanup before destroying the object.
        """
        print(f"[ActiveNote] Closing session for {self.note_id}")
        self._observer.stop()
        self._observer.join()

        if self._save_timer:
            self._save_timer.cancel()

        if self.is_dirty:
            self._save_to_disk()


# ==========================================
# 3. The Manager (Singleton Registry)
# ==========================================
class NoteManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NoteManager, cls).__new__(cls)
            cls._instance.active_notes = {}
        return cls._instance

    def open_existing_note(self, note_id: str) -> ActiveNote:
        # 1. Return existing instance if open
        if note_id in self.active_notes:
            return self.active_notes[note_id]
        else:
            raise ValueError

    def create_new_note(self, note_id: str):
        try:
            new_note = ActiveNote(note_id)
            self.active_notes[note_id] = new_note
            return new_note
        except ValueError as e:
            print(e)
            return None

    def close_note(self, note_id: str):
        if note_id in self.active_notes:
            self.active_notes[note_id].close()
            del self.active_notes[note_id]

    def get_all_active_notes(self) -> List[ActiveNote]:
        return list(self.active_notes.values())

'''
# ==========================================
# 4. Usage / Testing
# ==========================================
if __name__ == "__main__":
    # NOTE: This requires 'filesys' and 'cache_db' to be working and populated.

    manager = NoteManager()

    newnote = initialize_vault_scan(Path("C:/Users/ADMIN/Development/PyTauri/project sushi sandbox-vault/"))
    print(newnote)
    # 1. Grab an ID from your existing .jnote file
    # (Replace this with a real ID from your DB/Filesystem)
    TEST_ID = "4f1139b8-6f8c-4be2-9f57-64554805a267"

    print(f"--- Opening Note {TEST_ID} ---")
    note = manager.get_or_open_note(TEST_ID)

    if note:
        # 2. Simulate Frontend updating a block
        # We need a valid block ID from your file
        BLOCK_ID = "af176423-2d39-410e-b65e-7b908d5f76a6"

        print(f"--- Updating Block {BLOCK_ID} ---")
        new_data = {"content": "Updated via ActiveNote Manager!", "format": "markdown"}
        note.update_block(BLOCK_ID, new_data)

        # 3. Wait for Auto-Save
        print("Waiting for auto-save...")
        time.sleep(3)

        # 4. Clean up
        manager.close_note(TEST_ID)
'''