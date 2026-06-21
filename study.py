import os
import sys
import json
import sqlite3
import tempfile
import argparse
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional

# Ensure UTF-8 output on Windows terminal
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

# Determine paths dynamically
SCRIPT_DIR = Path(__file__).resolve().parent
PROGRESS_PATH = SCRIPT_DIR / "study_progress.json"

# ANSI Terminal Colors
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_BLUE = "\033[94m"
COLOR_RED = "\033[91m"
COLOR_CYAN = "\033[96m"
COLOR_RESET = "\033[0m"

def color_text(text: str, color: str) -> str:
    """Helper to apply terminal colors if stdout is a TTY."""
    if sys.stdout.isatty():
        return f"{color}{text}{COLOR_RESET}"
    return text

def find_db_path() -> Optional[Path]:
    # 1. Direct check in AppData/Local/npm-cache/_npx (where n8n-mcp runs from)
    appdata_local = os.environ.get("LOCALAPPDATA")
    if not appdata_local:
        appdata_local = str(Path.home() / "AppData" / "Local")
        
    npx_dir = Path(appdata_local) / "npm-cache" / "_npx"
    if npx_dir.exists():
        try:
            # List only hash folders under _npx directly
            for path in npx_dir.iterdir():
                if path.is_dir():
                    candidate_path = path / "node_modules" / "n8n-mcp" / "data" / "nodes.db"
                    if candidate_path.exists():
                        return candidate_path
        except OSError:
            pass
                    
    # 2. Fallback to scratch directory database (dynamically resolve user home)
    fallback = Path.home() / ".gemini" / "antigravity" / "scratch" / "n8n-mcp" / "data" / "nodes.db"
    if fallback.exists():
        return fallback
    return None

def get_template_info(template_id: str, db_path: Path) -> Tuple[str, str]:
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        c = conn.cursor()
        c.execute("SELECT name, description FROM templates WHERE id = ?", (template_id,))
        row = c.fetchone()
        if row:
            return row[0], row[1] or ""
    except sqlite3.Error:
        pass
    finally:
        if conn:
            conn.close()
    return "Unknown Template", ""

def load_data() -> Tuple[Dict[str, Any], Path]:
    data = {}
    if PROGRESS_PATH.exists():
        try:
            with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            # Corrupted file handling: backup the file and notify
            backup_path = PROGRESS_PATH.with_suffix(".corrupt.bak")
            try:
                PROGRESS_PATH.rename(backup_path)
                print(color_text(f"Warning: Progress file was corrupted. Backed up to {backup_path.name} and reset.", COLOR_YELLOW))
            except OSError:
                print(color_text("Warning: Progress file was corrupted and could not be backed up.", COLOR_RED))
            data = {}
        except OSError:
            data = {}
            
    db_path_str = data.get("db_path_cache")
    db_path = Path(db_path_str) if db_path_str else None
    
    if not db_path or not db_path.exists():
        db_path = find_db_path()
        if not db_path:
            print(color_text("Error: Database 'nodes.db' not found on the system.", COLOR_RED))
            sys.exit(1)
        data["db_path_cache"] = str(db_path)

    # Fetch DB modification time
    try:
        current_mtime = db_path.stat().st_mtime
    except OSError:
        current_mtime = 0.0

    cached_ids = data.get("ids", [])
    cached_mtime = data.get("db_mtime", 0.0)

    # Reload IDs if database has changed
    if not cached_ids or cached_mtime != current_mtime:
        conn = None
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            c = conn.cursor()
            c.execute("SELECT id FROM templates ORDER BY id ASC")
            db_ids = [row[0] for row in c.fetchall()]
            
            data["ids"] = db_ids
            data["db_mtime"] = current_mtime
            data.setdefault("completed_ids", [])
            data.setdefault("current_id", None)
            save_data(data)
        except sqlite3.Error as e:
            if cached_ids:
                pass
            else:
                print(color_text(f"Error reading database: {e}", COLOR_RED))
                sys.exit(1)
        finally:
            if conn:
                conn.close()
    else:
        data.setdefault("completed_ids", [])
        data.setdefault("current_id", None)

    return data, db_path

def save_data(data: Dict[str, Any]) -> None:
    """Writes progress atomically to prevent state corruption."""
    temp_fd, temp_path_str = tempfile.mkstemp(dir=str(PROGRESS_PATH.parent), suffix=".tmp")
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        temp_path.replace(PROGRESS_PATH)
    except Exception as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise e

def print_template(template_id: str, db_path: Path) -> None:
    name, desc = get_template_info(template_id, db_path)
    print(color_text(f"📖 Active Template: {template_id} - {name}", COLOR_CYAN))
    if desc:
        print(f"\n{color_text('Description:', COLOR_YELLOW)}\n{desc}\n")

def print_progress_bar(done: int, total: int, width: int = 30) -> str:
    """Generates a clean text-based progress bar."""
    if total == 0:
        return "[]"
    percent = done / total
    filled_len = int(width * percent)
    bar = "█" * filled_len + "░" * (width - filled_len)
    return f"[{bar}] {done}/{total} ({percent * 100:.2f}%)"

def main() -> None:
    data, db_path = load_data()
    ids = data["ids"]
    completed_ids = data["completed_ids"]
    current_id = data["current_id"]

    # Support bilingual aliases (Arabic & English)
    cmd_mapping = {
        "done": "done", "complete": "done", "خلصت": "done",
        "undo": "undo", "تراجع": "undo",
        "status": "status", "الحالة": "status"
    }

    parser = argparse.ArgumentParser(
        description="n8n Study Progress Tracker",
        add_help=True
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=list(cmd_mapping.keys()),
        help="Command to run: 'done' (complete study), 'undo' (rollback last), 'status' (view stats)."
    )
    
    args = parser.parse_args()
    
    if args.command is None:
        # Default behavior: show current active or fetch the next study template
        if current_id is not None:
            print_template(current_id, db_path)
        else:
            completed_set = set(completed_ids)
            next_id = None
            for tid in ids:
                if tid not in completed_set:
                    next_id = tid
                    break
            if next_id is not None:
                data["current_id"] = next_id
                save_data(data)
                print_template(next_id, db_path)
            else:
                print(color_text("🎉 Excellent job! All templates have been completed!", COLOR_GREEN))
        sys.exit(0)

    # Normalize command alias
    cmd = cmd_mapping[args.command.lower()]
    
    if cmd == "done":
        if current_id is not None:
            completed_ids.append(current_id)
            data["current_id"] = None
            save_data(data)
            print(color_text(f"✔️ Marked template {current_id} as completed.", COLOR_GREEN))
        else:
            print(color_text("⚠️ No active template under study. Type 'study' to fetch the next template.", COLOR_YELLOW))
            
    elif cmd == "undo":
        if completed_ids:
            last_id = completed_ids.pop()
            data["current_id"] = last_id
            save_data(data)
            print(color_text("↩️ Undone. Active template rolled back to:", COLOR_YELLOW))
            print_template(last_id, db_path)
        else:
            print(color_text("⚠️ No completed templates to undo.", COLOR_YELLOW))
            
    elif cmd == "status":
        total = len(ids)
        done_count = len(completed_ids)
        
        print("\n" + color_text("📈 Study Progress Report", COLOR_BLUE))
        print("=" * 40)
        print(color_text(print_progress_bar(done_count, total), COLOR_GREEN))
        print("=" * 40)
        
        if current_id is not None:
            print_template(current_id, db_path)
        else:
            print(color_text("Active Template: None", COLOR_YELLOW))
            
        if completed_ids:
            last_id = completed_ids[-1]
            last_name, _ = get_template_info(last_id, db_path)
            print(color_text(f"Last Completed: {last_id} - {last_name}", COLOR_YELLOW))
        print()

if __name__ == "__main__":
    main()
