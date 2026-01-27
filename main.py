import time
import sys
from pathlib import Path

# --- Architecture Imports ---
from filesys import VaultWatcher, localdb
from active_state import state_manager
from logger_service import sys_log, LogSource, LogLevel

# 1. Define your Vault Path
# Ensure this path actually exists on your machine!
NOTES_DIRECTORY = Path("C:/Users/ADMIN/Development/PyTauri/project sushi sandbox-vault/")


def main():
    print(f"--- 0. System Startup ---")

    if not NOTES_DIRECTORY.exists():
        sys_log.log(LogSource.SYSTEM, LogLevel.CRITICAL, f"Path not found: {NOTES_DIRECTORY}")
        return

    # 2. Initialize and Start the Vault Watcher
    # This automatically runs the initial scan and populates the SQLite DB
    print(f"--- 1. Starting Vault Watcher for: {NOTES_DIRECTORY} ---")
    watcher = VaultWatcher(NOTES_DIRECTORY)
    watcher.start()

    # Give the watcher a moment to finish the initial scan logic
    time.sleep(0.5)
    print("Watcher started and DB populated.\n")

    # 3. Retrieve all notes from the DB (via Filesys -> CacheDB)
    all_notes = localdb.get_all_notes()

    if not all_notes:
        print("No notes found in the vault! Make sure you have .jnote files there.")
        watcher.stop()
        return

    # 4. Interactive Selection
    print("--- 2. Available Notes ---")
    for index, note_meta in enumerate(all_notes):
        # Note: note_meta is now a Dataclass, so we use dot notation
        print(f"[{index}] {note_meta.note_title} (ID: {note_meta.note_id})")

    try:
        choice = int(input("\nEnter the number of the note to open: "))
        selected_meta = all_notes[choice]
    except (ValueError, IndexError):
        print("Invalid selection.")
        watcher.stop()
        return

    print(f"\n--- 3. Opening Note: {selected_meta.note_title} ---")

    # 5. Open via StateManager (The Brain)
    # This loads the JNote object into memory
    active_note = state_manager.get_or_open_note(selected_meta.note_id)

    if not active_note:
        print("Failed to open note.")
        watcher.stop()
        return

    # 6. Display Current Content
    # active_note.note_obj is the strict JNote dataclass
    current_blocks = active_note.note_obj.blocks
    print(f"Successfully loaded {len(current_blocks)} blocks.")
    print("Current Blocks Data:")

    for block in current_blocks:
        # block is a NoteBlock object. Access data via attributes.
        # content is stored inside the 'data' dictionary.
        content_preview = block.data.get('content', '')[:40]
        print(f" - [{block.type}] {content_preview}...")

    # 7. Simulate an Edit (Add a Block)
    print("\n--- 4. Simulating User Edit (Adding a Block) ---")

    # We pass 'content' as a kwarg because BlockFactory._create_text_block expects it
    new_block = active_note.add_block(
        block_type="text",
        content=f"Test Block added via Backend at {time.strftime('%H:%M:%S')}"
    )

    print(f"Block added! Dirty state: {active_note.is_dirty}")

    # 8. Wait for Auto-Save
    # The ActiveNote has a 2.0 second timer. We wait 3.5s to be safe.
    print("\n--- 5. Waiting 3.5 seconds for Auto-Save to trigger... ---")
    time.sleep(3.5)

    # 9. Cleanup
    print("\n--- 6. Cleanup & Closing ---")
    state_manager.close_note(selected_meta.note_id)
    watcher.stop()
    print("Test complete. Check your .jnote file to see the new block!")


if __name__ == "__main__":
    main()