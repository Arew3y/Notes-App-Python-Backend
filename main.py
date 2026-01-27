import time
import filesys
import active_state
from pathlib import Path

# 1. Define your Vault Path
NOTES_DIRECTORY = Path("C:/Users/ADMIN/Development/PyTauri/project sushi sandbox-vault/")

def main():
    print(f"--- 1. Initializing Vault Scan for: {NOTES_DIRECTORY} ---")
    # This populates the SQLite DB with the files found on disk
    filesys.initialize_vault_scan(NOTES_DIRECTORY)
    print("Scan complete.\n")

    # 2. Retrieve all notes from the DB
    all_notes = filesys.localdb.get_all_notes()

    if not all_notes:
        print("No notes found in the vault! Make sure you have .jnote files there.")
        return

    # 3. Interactive Selection
    print("--- 2. Available Notes ---")
    for index, note_meta in enumerate(all_notes):
        print(f"[{index}] {note_meta.note_title} (ID: {note_meta.note_id})")

    try:
        choice = int(input("\nEnter the number of the note to open: "))
        selected_meta = all_notes[choice]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return

    print(f"\n--- 3. Opening Note: {selected_meta.note_title} ---")

    # Initialize the Manager
    manager = active_state .NoteManager()

    # Open the note (This loads it from disk into memory)
    active_note_instance = manager.get_or_open_note(selected_meta.note_id)

    if not active_note_instance:
        print("Failed to open note.")
        return

    # 4. Display Current Content
    print(f"Successfully loaded {len(active_note_instance.blocks)} blocks.")
    print("Current Blocks Data:")
    for block in active_note_instance.blocks:
        print(f" - [{block.get('type')}] {block.get('data', {}).get('content', '')[:30]}...")

    # 5. Simulate an Edit (Add a Block)
    print("\n--- 4. Simulating User Edit (Adding a Block) ---")
    new_block = active_note_instance.add_block(
        block_type="text",
    )
    print(f"Block added! Dirty state: {active_note_instance.is_dirty}")

    # 6. Wait for Auto-Save
    # The active_note module has a 2-second debounce timer.
    # We must keep the script alive long enough for the timer to fire.
    print("\n--- 5. Waiting 3 seconds for Auto-Save to trigger... ---")
    time.sleep(3)

    # 7. Cleanup
    print("\n--- 6. Closing Note ---")
    manager.close_note(selected_meta.note_id)
    print("Test complete. Check your .jnote file to see the new block!")


if __name__ == "__main__":
    main()