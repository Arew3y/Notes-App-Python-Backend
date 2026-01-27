import os
import sqlite3
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Union
from logger_service import sys_log, LogSource, LogLevel


@dataclass
class NoteMetadata:
    note_id: str
    note_title: str
    note_version: str
    note_dir: Path

    def __post_init__(self):
        if isinstance(self.note_dir, str):
            self.note_dir = Path(self.note_dir)


@dataclass
class DirectoryMetadata:
    dir_path: Path
    dir_name: str
    parent_path: Optional[Path] = None

    def __post_init__(self):
        if isinstance(self.dir_path, str):
            self.dir_path = Path(self.dir_path)
        if isinstance(self.parent_path, str) and self.parent_path:
            self.parent_path = Path(self.parent_path)


class FileIndex:
    def __init__(self, db_path: str = ":memory:"):
        # Log the connection attempt
        sys_log.log(LogSource.DB, LogLevel.INFO, f"Initializing DB connection at {db_path}")

        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._setup_db()

    def _setup_db(self):
        try:
            self.cursor.execute("""
                                CREATE TABLE IF NOT EXISTS notes
                                (
                                    note_id TEXT PRIMARY KEY,
                                    note_title TEXT,
                                    note_version TEXT,
                                    note_dir TEXT,
                                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                                )
                                """)
            self.cursor.execute("""
                                CREATE TABLE IF NOT EXISTS directories
                                (
                                    dir_path TEXT PRIMARY KEY,
                                    dir_name TEXT,
                                    parent_path TEXT
                                )
                                """)
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_parent_path ON directories(parent_path)")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_note_dir ON notes(note_dir)")
            self.conn.commit()
        except Exception as e:
            # Critical because if tables fail, the app fails
            sys_log.log(LogSource.DB, LogLevel.CRITICAL, "Failed to setup DB tables",
                        meta={"error": str(e)})
            raise e

    # ==========================
    # Read Operations
    # ==========================
    def get_directory_contents(self, target_path: Union[str, Path]) -> Dict[str, List]:
        # Reads are often noisy, so we use DEBUG level
        sys_log.log(LogSource.DB, LogLevel.DEBUG, f"Fetching contents for {target_path}")

        target_str = str(target_path)
        self.cursor.execute("SELECT dir_path, dir_name FROM directories WHERE parent_path = ?", (target_str,))
        sub_dirs = [{'path': r[0], 'name': r[1], 'type': 'folder'} for r in self.cursor.fetchall()]

        self.cursor.execute("SELECT note_id, note_title FROM notes WHERE note_dir = ?", (target_str,))
        notes = [{'id': r[0], 'name': r[1], 'type': 'file'} for r in self.cursor.fetchall()]

        return {'path': target_str, 'folders': sub_dirs, 'files': notes}

    def get_metadata(self, note_id: str) -> Optional[NoteMetadata]:
        sys_log.log(LogSource.DB, LogLevel.DEBUG, f"Fetching metadata for NoteID {note_id}")

        self.cursor.execute("SELECT * FROM notes WHERE note_id = ?", (note_id,))
        row = self.cursor.fetchone()
        if row:
            sys_log.log(LogSource.DB, LogLevel.DEBUG, f"Fetching metadata for NoteID {note_id} : SUCCESS")
            return NoteMetadata(row[0], row[1], row[2], Path(row[3]))
        sys_log.log(LogSource.DB, LogLevel.ERROR, f"Fetching metadata for NoteID {note_id} : FAILED")
        return None

    def get_all_notes(self) -> Optional[List[NoteMetadata]]:
        sys_log.log(LogSource.DB, LogLevel.DEBUG, f"Fetching metadata for all notes")

        self.cursor.execute("SELECT note_id, note_title, note_version, note_dir FROM notes")

        try:
            sys_log.log(LogSource.DB, LogLevel.DEBUG, f"Fetching metadata for all notes : SUCCESS")
            return [NoteMetadata(r[0], r[1], r[2], Path(r[3])) for r in self.cursor.fetchall()]
        except Exception as e:
            sys_log.log(
                LogSource.DB,
                LogLevel.ERROR,
                "Fetching metadata for all notes : FAILED",
                meta={"error": str(e)}
            )


    # ==========================
    # Write Operations
    # ==========================
    def add_directory(self, directory: DirectoryMetadata) -> bool:
        try:
            data = {
                'dir_path': str(directory.dir_path),
                'dir_name': directory.dir_name,
                'parent_path': str(directory.parent_path) if directory.parent_path else None
            }
            self.cursor.execute("""
                INSERT OR REPLACE INTO directories (dir_path, dir_name, parent_path)
                VALUES (:dir_path, :dir_name, :parent_path)
            """, data)
            self.conn.commit()

            # Log SUCCESS
            sys_log.log(LogSource.DB, LogLevel.INFO, f"Directory added: {directory.dir_name}")
            return True

        except sqlite3.IntegrityError as e:
            # Log FAILURE
            sys_log.log(LogSource.DB, LogLevel.ERROR, "Directory write failed (Integrity)",
                        meta={"error": str(e), "path": str(directory.dir_path)})
            return False

    def add_metadata(self, note: NoteMetadata) -> bool:
        try:
            data = asdict(note)
            data['note_dir'] = str(data['note_dir'])
            self.cursor.execute("""
                INSERT OR REPLACE INTO notes (note_id, note_title, note_version, note_dir)
                VALUES (:note_id, :note_title, :note_version, :note_dir)
            """, data)
            self.conn.commit()

            # Log SUCCESS
            sys_log.log(LogSource.DB, LogLevel.INFO, f"Note metadata saved: {note.note_title}")
            return True

        except sqlite3.IntegrityError as e:
            # Log FAILURE
            sys_log.log(LogSource.DB, LogLevel.ERROR, "Note write failed (Integrity)",
                        meta={"error": str(e), "id": note.note_id})
            return False

    # ==========================
    # New: Moved SQL Logic
    # ==========================

    def delete_note(self, note_id: str):
        """Deletes a single note by ID."""
        try:
            self.cursor.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
            self.conn.commit()
            sys_log.log(LogSource.DB, LogLevel.INFO, f"Deleted note: {note_id}")
        except Exception as e:
            sys_log.log(LogSource.DB, LogLevel.ERROR, f"Failed to delete note: {note_id}",
                        meta={"error": str(e)})

    def delete_directory_recursive(self, dir_path: str):
        """
        Deletes the directory, ALL sub-directories, and ALL notes inside them.
        Uses LIKE 'path/ %' to find children (fixing the prefix bug).
        """
        import os  # Ensure os is imported for separator handling

        try:
            # 1. Log Intent (Warn because it's destructive)
            sys_log.log(LogSource.DB, LogLevel.WARNING, f"Recursive delete triggered for: {dir_path}")

            # --- CRITICAL FIX ---
            # We must append a separator (e.g., '/') to ensure we only match children.
            # Without this, deleting ".../Project" would also delete ".../ProjectBackup"
            safe_child_prefix = os.path.join(str(dir_path), "")

            # Delete notes in sub-folders (Use safe_child_prefix)
            self.cursor.execute("DELETE FROM notes WHERE note_dir LIKE ? || '%'", (safe_child_prefix,))
            notes_sub_count = self.cursor.rowcount

            # Delete notes in this folder (Exact match)
            self.cursor.execute("DELETE FROM notes WHERE note_dir = ?", (dir_path,))
            notes_curr_count = self.cursor.rowcount

            # Delete sub-folders (Use safe_child_prefix)
            self.cursor.execute("DELETE FROM directories WHERE dir_path LIKE ? || '%'", (safe_child_prefix,))
            dirs_sub_count = self.cursor.rowcount

            # Delete the folder itself (Exact match)
            self.cursor.execute("DELETE FROM directories WHERE dir_path = ?", (dir_path,))
            dirs_curr_count = self.cursor.rowcount

            self.conn.commit()

            # 2. Log Success with stats
            total_notes = notes_sub_count + notes_curr_count
            total_dirs = dirs_sub_count + dirs_curr_count

            sys_log.log(
                LogSource.DB,
                LogLevel.INFO,
                f"Recursive delete complete for {dir_path}",
                meta={"deleted_notes": total_notes, "deleted_dirs": total_dirs}
            )

        except Exception as e:
            # 3. Log Failure
            sys_log.log(
                LogSource.DB,
                LogLevel.ERROR,
                f"Failed recursive delete for {dir_path}",
                meta={"error": str(e)}
            )
            # Re-raise so the UI knows it failed
            raise e

    def update_directory(self, old_path: str, new_path: str, new_name: str):
        """
        Renames a directory and updates all children (files and subfolders)
        to point to the new path.
        """
        try:
            sys_log.log(LogSource.DB, LogLevel.INFO, f"Renaming dir from {old_path} to {new_path}")

            # 1. Update the folder itself
            self.cursor.execute(
                "UPDATE directories SET dir_path = ?, dir_name = ? WHERE dir_path = ?",
                (new_path, new_name, old_path)
            )

            # 2. Update ALL sub-directories (Recursive fix using string replacement)
            # Replaces 'C:/Old/Child' with 'C:/New/Child'
            self.cursor.execute("""
                                UPDATE directories
                                SET dir_path    = replace(dir_path, ?, ?),
                                    parent_path = replace(parent_path, ?, ?)
                                WHERE dir_path LIKE ? || '%'
                                """, (old_path, new_path, old_path, new_path, old_path))

            # 3. Update notes in this folder and sub-folders
            self.cursor.execute("""
                                UPDATE notes
                                SET note_dir = replace(note_dir, ?, ?)
                                WHERE note_dir = ?
                                   OR note_dir LIKE ? || '%'
                                """, (old_path, new_path, old_path, old_path))

            self.conn.commit()

            sys_log.log(LogSource.DB, LogLevel.DEBUG, "Recursive path update complete.")

        except Exception as e:
            sys_log.log(LogSource.DB, LogLevel.ERROR, "Directory rename failed",
                        meta={"error": str(e), "old": old_path, "new": new_path})

