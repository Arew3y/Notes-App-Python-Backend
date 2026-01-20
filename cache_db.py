import sqlite3
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Union


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
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._setup_db()

    def _setup_db(self):
        self.cursor.execute("""
                            CREATE TABLE IF NOT EXISTS notes
                            (
                                note_id
                                TEXT
                                PRIMARY
                                KEY,
                                note_title
                                TEXT,
                                note_version
                                TEXT,
                                note_dir
                                TEXT,
                                updated_at
                                DATETIME
                                DEFAULT
                                CURRENT_TIMESTAMP
                            )
                            """)
        self.cursor.execute("""
                            CREATE TABLE IF NOT EXISTS directories
                            (
                                dir_path
                                TEXT
                                PRIMARY
                                KEY,
                                dir_name
                                TEXT,
                                parent_path
                                TEXT
                            )
                            """)
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_parent_path ON directories(parent_path)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_note_dir ON notes(note_dir)")
        self.conn.commit()

    # ==========================
    # Read Operations
    # ==========================
    def get_directory_contents(self, target_path: Union[str, Path]) -> Dict[str, List]:
        target_str = str(target_path)
        self.cursor.execute("SELECT dir_path, dir_name FROM directories WHERE parent_path = ?", (target_str,))
        sub_dirs = [{'path': r[0], 'name': r[1], 'type': 'folder'} for r in self.cursor.fetchall()]

        self.cursor.execute("SELECT note_id, note_title FROM notes WHERE note_dir = ?", (target_str,))
        notes = [{'id': r[0], 'name': r[1], 'type': 'file'} for r in self.cursor.fetchall()]

        return {'path': target_str, 'folders': sub_dirs, 'files': notes}

    def get_metadata(self, nt_id: str) -> Optional[NoteMetadata]:
        self.cursor.execute("SELECT * FROM notes WHERE note_id = ?", (nt_id,))
        row = self.cursor.fetchone()
        if row:
            return NoteMetadata(row[0], row[1], row[2], Path(row[3]))
        return None

    def get_all_notes(self) -> List[NoteMetadata]:
        self.cursor.execute("SELECT note_id, note_title, note_version, note_dir FROM notes")
        return [NoteMetadata(r[0], r[1], r[2], Path(r[3])) for r in self.cursor.fetchall()]

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
            return True
        except sqlite3.IntegrityError:
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
            return True
        except sqlite3.IntegrityError:
            return False

    # ==========================
    # New: Moved SQL Logic
    # ==========================

    def delete_note(self, note_id: str):
        """Deletes a single note by ID."""
        self.cursor.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
        self.conn.commit()

    def delete_directory_recursive(self, dir_path: str):
        """
        Deletes the directory, ALL sub-directories, and ALL notes inside them.
        Uses LIKE 'path%' to find children.
        """
        # Delete notes in sub-folders
        self.cursor.execute("DELETE FROM notes WHERE note_dir LIKE ? || '%'", (dir_path,))
        # Delete notes in this folder
        self.cursor.execute("DELETE FROM notes WHERE note_dir = ?", (dir_path,))

        # Delete sub-folders
        self.cursor.execute("DELETE FROM directories WHERE dir_path LIKE ? || '%'", (dir_path,))
        # Delete the folder itself
        self.cursor.execute("DELETE FROM directories WHERE dir_path = ?", (dir_path,))

        self.conn.commit()

    def update_directory(self, old_path: str, new_path: str, new_name: str):
        """
        Renames a directory and updates all children (files and subfolders)
        to point to the new path.
        """
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