import os
import sys
import json
import sqlite3
import tempfile
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
    appdata_local = os.environ.get("LOCALAPPDATA")
    if not appdata_local:
        appdata_local = str(Path.home() / "AppData" / "Local")
        
    npx_dir = Path(appdata_local) / "npm-cache" / "_npx"
    if npx_dir.exists():
        try:
            for path in npx_dir.iterdir():
                if path.is_dir():
                    candidate_path = path / "node_modules" / "n8n-mcp" / "data" / "nodes.db"
                    if candidate_path.exists():
                        return candidate_path
        except OSError:
            pass
                    
    fallback = Path.home() / ".gemini" / "antigravity" / "scratch" / "n8n-mcp" / "data" / "nodes.db"
    if fallback.exists():
        return fallback
    return None

def get_template_info(template_id: int, db_path: Path) -> Tuple[str, str, int, str, str, int, str, str]:
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        c = conn.cursor()
        c.execute("""
            SELECT name, description, views, categories, author_name, author_verified, nodes_used, url 
            FROM templates WHERE id = ?
        """, (template_id,))
        row = c.fetchone()
        if row:
            return (
                row[0] or "Unknown", 
                row[1] or "", 
                row[2] or 0, 
                row[3] or "General", 
                row[4] or "n8n", 
                row[5] or 0, 
                row[6] or "[]", 
                row[7] or ""
            )
    except sqlite3.Error:
        pass
    finally:
        if conn:
            conn.close()
    return "Unknown Template", "", 0, "General", "n8n", 0, "[]", ""

def get_node_info(node_type: str, db_path: Path) -> Tuple[str, str, str, str, int, str, int, int, int, int, str]:
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        c = conn.cursor()
        c.execute("""
            SELECT display_name, description, category, npm_package_name, npm_downloads, npm_version, 
                   is_verified, is_ai_tool, is_trigger, is_webhook, documentation 
            FROM nodes WHERE node_type = ?
        """, (node_type,))
        row = c.fetchone()
        if row:
            return (
                row[0] or "Unknown", 
                row[1] or "", 
                row[2] or "General", 
                row[3] or "", 
                row[4] or 0, 
                row[5] or "latest", 
                row[6] or 0,
                row[7] or 0,
                row[8] or 0,
                row[9] or 0,
                row[10] or ""
            )
    except sqlite3.Error:
        pass
    finally:
        if conn:
            conn.close()
    return "Unknown Node", "", "General", "", 0, "latest", 0, 0, 0, 0, ""

def load_data() -> Tuple[Dict[str, Any], Path]:
    data = {}
    if PROGRESS_PATH.exists():
        try:
            with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
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

    try:
        current_mtime = db_path.stat().st_mtime
    except OSError:
        current_mtime = 0.0

    # Ensure separate modes in data
    for mode in ("templates", "nodes"):
        if mode not in data or not isinstance(data[mode], dict):
            data[mode] = {
                "ids": [],
                "completed_ids": [],
                "current_id": None,
                "db_mtime": 0.0
            }

    # Sync templates
    t_data = data["templates"]
    if not t_data.get("ids") or t_data.get("db_mtime", 0.0) != current_mtime:
        conn = None
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            c = conn.cursor()
            c.execute("SELECT id FROM templates WHERE author_verified = 1 ORDER BY id ASC")
            t_data["ids"] = [row[0] for row in c.fetchall()]
            t_data["db_mtime"] = current_mtime
            save_data(data)
        except sqlite3.Error as e:
            if not t_data.get("ids"):
                print(color_text(f"Error reading templates database: {e}", COLOR_RED))
                sys.exit(1)
        finally:
            if conn:
                conn.close()

    # Sync nodes
    n_data = data["nodes"]
    if not n_data.get("ids") or n_data.get("db_mtime", 0.0) != current_mtime:
        conn = None
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            c = conn.cursor()
            c.execute("SELECT node_type FROM nodes WHERE is_verified = 1 ORDER BY node_type ASC")
            n_data["ids"] = [row[0] for row in c.fetchall()]
            n_data["db_mtime"] = current_mtime
            save_data(data)
        except sqlite3.Error as e:
            if not n_data.get("ids"):
                print(color_text(f"Error reading nodes database: {e}", COLOR_RED))
                sys.exit(1)
        finally:
            if conn:
                conn.close()

    return data, db_path

def save_data(data: Dict[str, Any]) -> None:
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

def print_template(template_id: int, db_path: Path) -> None:
    name, desc, views, categories, author, author_verified, nodes_used_json, url = get_template_info(template_id, db_path)
    
    # Format nodes used
    try:
        nodes_list = json.loads(nodes_used_json)
        cleaned_nodes = []
        for n in nodes_list:
            if n.startswith("n8n-nodes-base."):
                cleaned_nodes.append(n[len("n8n-nodes-base."):])
            elif n.startswith("@n8n/n8n-nodes-langchain."):
                cleaned_nodes.append(n[len("@n8n/n8n-nodes-langchain."):])
            else:
                cleaned_nodes.append(n)
        unique_nodes = sorted(list(set(cleaned_nodes)))
        nodes_used_str = ", ".join(unique_nodes) if unique_nodes else "None"
    except:
        nodes_used_str = "None"
        
    verified_status = "Yes" if author_verified else "No"
    
    print(color_text(f"📖 Active Template: {template_id} - {name}", COLOR_CYAN))
    print(f"📊 Views: {views} | 🏷️ Categories: {categories} | 👤 Author: {author} (Verified: {verified_status})")
    print(f"🛠️ Nodes Used: {nodes_used_str}")
    print(f"🔗 URL: {url or f'https://n8n.io/workflows/{template_id}'}")
    if desc:
        print(f"\n{color_text('Description:', COLOR_YELLOW)}\n{desc}\n")

def print_node(node_type: str, db_path: Path) -> None:
    display_name, desc, category, npm_package, npm_downloads, npm_version, is_verified, is_ai_tool, is_trigger, is_webhook, doc = get_node_info(node_type, db_path)
    
    verified_status = "Yes" if is_verified else "No"
    
    # Build attributes list
    attrs = []
    if is_trigger:
        attrs.append("Trigger")
    if is_webhook:
        attrs.append("Webhook")
    if is_ai_tool:
        attrs.append("AI Tool")
    attr_str = ", ".join(attrs) if attrs else "Standard"
    
    print(color_text(f"🛠️ Active Node: {display_name}", COLOR_CYAN))
    print(f"🆔 Type: {node_type} | 🏷️ Category: {category} | 🛡️ Verified: {verified_status}")
    print(f"⚙️ Attributes: {attr_str}")
    if npm_package:
        print(f"📦 NPM Package: {npm_package} ({npm_version}) | 📥 Downloads: {npm_downloads}")
    if desc:
        print(f"📝 Description: {desc}")
    if doc:
        print(f"\n{color_text('Documentation:', COLOR_YELLOW)}\n{doc}\n")

def print_progress_bar(done: int, total: int, width: int = 30) -> str:
    if total == 0:
        return "[]"
    percent = done / total
    filled_len = int(width * percent)
    bar = "█" * filled_len + "░" * (width - filled_len)
    return f"[{bar}] {done}/{total} ({percent * 100:.2f}%)"

def show_mode_status(mode: str, data: Dict[str, Any], db_path: Path):
    m_data = data[mode]
    ids = m_data["ids"]
    completed_ids = m_data["completed_ids"]
    current_id = m_data["current_id"]
    total = len(ids)
    done_count = len(completed_ids)
    
    title = "📖 Templates Progress" if mode == "templates" else "🛠️ Nodes Progress"
    print("\n" + color_text(title, COLOR_BLUE))
    print("=" * 40)
    print(color_text(print_progress_bar(done_count, total), COLOR_GREEN))
    print("=" * 40)
    
    if current_id is not None:
        if mode == "templates":
            print_template(current_id, db_path)
        else:
            print_node(current_id, db_path)
    else:
        print(color_text("Active Item: None", COLOR_YELLOW))
        
    if completed_ids:
        last_id = completed_ids[-1]
        if mode == "templates":
            last_name, _, _, _, _, _ = get_template_info(last_id, db_path)
        else:
            last_name, _, _, _, _, _, _ = get_node_info(last_id, db_path)
        print(color_text(f"Last Completed: {last_id} - {last_name}", COLOR_YELLOW))
    print()

def print_help():
    print(color_text("n8n Study Progress Tracker", COLOR_BLUE))
    print("=" * 60)
    print("Usage:")
    print(f"  {color_text('study template [done/undo/status]', COLOR_CYAN)}")
    print("    Study official workflow templates")
    print(f"  {color_text('study node [done/undo/status]', COLOR_CYAN)}")
    print("    Study n8n core and community nodes")
    print(f"  {color_text('study status', COLOR_CYAN)}")
    print("    Show overall progress summary for both templates and nodes")
    print(f"  {color_text('study done', COLOR_CYAN)}")
    print("    Complete active item (template or node) automatically")
    print(f"  {color_text('study undo', COLOR_CYAN)}")
    print("    Rollback last completed item")
    print("-" * 60)
    print("Command Aliases:")
    print("  * Modes: template, templates, t")
    print("  * Modes: node, nodes, n")
    print("  * Subcommands: done, complete")
    print("  * Subcommands: undo")
    print("  * Subcommands: status")
    print("=" * 60)

def main() -> None:
    # Check for help command first
    if len(sys.argv) < 2 or sys.argv[1].lower() in ("help", "--help", "-h"):
        print_help()
        sys.exit(0)

    data, db_path = load_data()

    # Mappings
    mode_mapping = {
        "template": "templates", "templates": "templates", "t": "templates",
        "node": "nodes", "nodes": "nodes", "n": "nodes"
    }
    
    cmd_mapping = {
        "done": "done", "complete": "done",
        "undo": "undo",
        "status": "status"
    }

    first_arg = sys.argv[1].lower()
    
    mode = None
    cmd = None

    if first_arg in mode_mapping:
        mode = mode_mapping[first_arg]
        if len(sys.argv) >= 3:
            second_arg = sys.argv[2].lower()
            if second_arg in cmd_mapping:
                cmd = cmd_mapping[second_arg]
            else:
                print(color_text(f"Unknown command: {sys.argv[2]}", COLOR_RED))
                sys.exit(1)
    elif first_arg in cmd_mapping:
        cmd = cmd_mapping[first_arg]
        # Auto-detect mode based on which has an active current_id
        t_active = data["templates"]["current_id"] is not None
        n_active = data["nodes"]["current_id"] is not None
        if t_active and not n_active:
            mode = "templates"
        elif n_active and not t_active:
            mode = "nodes"
        elif cmd == "status":
            # Show both status if no mode specified
            show_mode_status("templates", data, db_path)
            show_mode_status("nodes", data, db_path)
            sys.exit(0)
        else:
            print(color_text("Multiple/No active items. Please specify: 'study template done' or 'study node done'.", COLOR_YELLOW))
            sys.exit(1)
    else:
        print(color_text(f"Unknown mode or command: {sys.argv[1]}", COLOR_RED))
        sys.exit(1)

    m_data = data[mode]
    ids = m_data["ids"]
    completed_ids = m_data["completed_ids"]
    current_id = m_data["current_id"]

    if cmd is None:
        # Default behavior: show current active or fetch the next study item
        if current_id is not None:
            if mode == "templates":
                print_template(current_id, db_path)
            else:
                print_node(current_id, db_path)
        else:
            completed_set = set(completed_ids)
            next_id = None
            for tid in ids:
                if tid not in completed_set:
                    next_id = tid
                    break
            if next_id is not None:
                m_data["current_id"] = next_id
                save_data(data)
                if mode == "templates":
                    print_template(next_id, db_path)
                else:
                    print_node(next_id, db_path)
            else:
                print(color_text(f"🎉 Excellent job! All {mode} have been completed!", COLOR_GREEN))
        sys.exit(0)

    if cmd == "done":
        if current_id is not None:
            completed_ids.append(current_id)
            m_data["current_id"] = None
            save_data(data)
            print(color_text(f"✔️ Marked {mode[:-1]} {current_id} as completed.", COLOR_GREEN))
        else:
            print(color_text(f"⚠️ No active {mode[:-1]} under study. Type 'study {mode[:-1]}' to fetch the next.", COLOR_YELLOW))
            
    elif cmd == "undo":
        if completed_ids:
            last_id = completed_ids.pop()
            m_data["current_id"] = last_id
            save_data(data)
            print(color_text(f"↩️ Undone. Active {mode[:-1]} rolled back to:", COLOR_YELLOW))
            if mode == "templates":
                print_template(last_id, db_path)
            else:
                print_node(last_id, db_path)
        else:
            print(color_text(f"⚠️ No completed {mode} to undo.", COLOR_YELLOW))
            
    elif cmd == "status":
        show_mode_status(mode, data, db_path)

if __name__ == "__main__":
    main()
