#!/usr/bin/env python3
"""
chatgpt-offboard: Export all ChatGPT conversations to Markdown

Exports to:
  exports/                          regular conversations
  exports/gpts/{gpt-name}/          conversations with a custom GPT
  exports/projects/{project-name}/  conversations inside a Project folder

Setup:
  pip3 install playwright
  python3 -m playwright install chromium

Run:
  python3 offboard.py
"""

import re
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE_DIR = "./browser_profile"  # persists login between runs
OUTPUT_DIR  = Path("exports")
DELAY       = 0.2  # seconds between API calls

# ── Auth ──────────────────────────────────────────────────────────────────────

def get_token(page):
    """Get a fresh Bearer token from the browser's active session."""
    token = page.evaluate("""
        async () => {
            const resp = await fetch('/api/auth/session');
            if (!resp.ok) return null;
            return (await resp.json()).accessToken || null;
        }
    """)
    if not token:
        raise RuntimeError("Could not get access token. Make sure you are logged in.")
    return token

def get_workspace_id(page):
    """Read the active account/workspace ID from localStorage."""
    return page.evaluate("() => localStorage.getItem('_account') || ''")

# ── Fetch helper ──────────────────────────────────────────────────────────────

def fetch_json(page, token, path):
    """Run a fetch() inside the browser so Cloudflare sees a real browser."""
    return page.evaluate("""
        async ([url, headers]) => {
            const resp = await fetch(url, { headers });
            if (!resp.ok) {
                const body = await resp.text();
                throw new Error("HTTP " + resp.status + " " + resp.statusText
                                + ": " + body.slice(0, 200));
            }
            return resp.json();
        }
    """, [f"https://chatgpt.com{path}", {"Authorization": f"Bearer {token}"}])

# ── Sidebar scroll ────────────────────────────────────────────────────────────

def scroll_sidebar(page, ticks=20):
    """Scroll the conversation sidebar to force lazy-loading of all entries."""
    for _ in range(ticks):
        page.evaluate("""
            () => {
                const sidebar = document.querySelector('nav') ||
                                document.querySelector('[data-testid="conversation-list"]') ||
                                document.querySelector('ol');
                if (sidebar) sidebar.scrollTop += 2000;
                else window.scrollBy(0, 2000);
            }
        """)
        page.wait_for_timeout(400)

# ── Conversation list ─────────────────────────────────────────────────────────

def read_convos_from_localstorage(page):
    """Read the conversation-history cache from localStorage."""
    raw = page.evaluate("""
        () => {
            const key = Object.keys(localStorage).find(k => k.includes('conversation-history'));
            return key ? localStorage.getItem(key) : null;
        }
    """)
    if not raw:
        return []
    convos = []
    data   = json.loads(raw)
    for pg in data.get("value", {}).get("pages", []):
        for item in pg.get("items", []):
            convos.append({
                "id":       item.get("id"),
                "title":    item.get("title") or "Untitled",
                "created":  item.get("create_time") or 0,
                "gizmo_id": item.get("gizmo_id"),
            })
    return convos

def get_all_conversations_from_api(page, token, workspace_id="", is_archived=False):
    """Paginate through the conversations API. Set is_archived=True for archived conversations."""
    convos  = []
    offset  = 0
    limit   = 100
    archive_param = "&is_archived=true" if is_archived else ""
    while True:
        base_params = f"offset={offset}&limit={limit}&order=updated{archive_param}"
        if workspace_id:
            base_params += f"&workspace_id={workspace_id}"
        data  = fetch_json(page, token, f"/backend-api/conversations?{base_params}")
        items = data.get("items", [])
        for item in items:
            convos.append({
                "id":       item.get("id"),
                "title":    item.get("title") or "Untitled",
                "created":  item.get("create_time") or 0,
                "gizmo_id": item.get("gizmo_id"),
            })
        total   = data.get("total", 0)
        offset += len(items)
        if not items or offset >= total:
            break
    if total and len(convos) < total:
        print(f"  !! Warning: API reported {total} conversations but only returned {len(convos)}.")
        print(f"     Some conversations may be inaccessible via the API.")
    return convos

# ── GPT name lookup ───────────────────────────────────────────────────────────

def get_gpt_names(page, token, gizmo_ids):
    """Look up display names for custom GPT IDs."""
    names = {}
    for gid in gizmo_ids:
        try:
            data      = fetch_json(page, token, f"/backend-api/gizmos/{gid}")
            names[gid] = data.get("gizmo", {}).get("display", {}).get("name") or gid
        except Exception:
            names[gid] = gid
    return names

# ── Project (folder) helpers ──────────────────────────────────────────────────

def get_projects_from_localstorage(page):
    """
    Read Project folder IDs from the snorlax-history localStorage cache.
    Returns list of {id, name} dicts.
    """
    raw = page.evaluate("""
        () => {
            const key = Object.keys(localStorage).find(k => k.includes('snorlax-history'));
            return key ? localStorage.getItem(key) : null;
        }
    """)
    if not raw:
        return []
    projects = []
    seen     = set()
    data     = json.loads(raw)
    for pg in data.get("value", {}).get("pages", []):
        for item in pg.get("items", []):
            gizmo = item.get("gizmo", {}).get("gizmo", {})
            gid   = gizmo.get("id", "")
            if gid.startswith("g-p-") and gid not in seen:
                name = (gizmo.get("display", {}) or {}).get("name") or ""
                projects.append({"id": gid, "name": name})
                seen.add(gid)
    return projects

def get_project_conversations(page, token, project_id):
    """
    Fetch all conversations for a Project folder.
    Returns (convos, project_name).
    """
    # Try to get the project name
    name = ""
    try:
        data = fetch_json(page, token, f"/backend-api/gizmos/{project_id}")
        name = data.get("gizmo", {}).get("display", {}).get("name") or ""
    except Exception:
        pass

    convos = []
    offset = 0
    while True:
        # Note: this endpoint caps at 50 per page
        data  = fetch_json(page, token,
                    f"/backend-api/gizmos/{project_id}/conversations"
                    f"?offset={offset}&limit=50")
        items = data.get("items", [])
        for item in items:
            convos.append({
                "id":      item.get("id"),
                "title":   item.get("title") or "Untitled",
                "created": item.get("create_time") or 0,
            })
        total   = data.get("total")
        offset += len(items)
        if not items or len(items) < 50:
            break
        if total is not None and offset >= total:
            break

    return convos, name

# ── Export ────────────────────────────────────────────────────────────────────

def save_conversations(page, token, convos, out_dir, label=""):
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = skipped = errors = 0
    for convo in convos:
        cid      = convo["id"]
        title    = convo["title"]
        created  = convo["created"]
        archived = convo.get("archived", False)

        date_prefix   = parse_date(created).strftime("%Y-%m-%d")
        archive_suffix = "_archived" if archived else ""
        filepath      = out_dir / f"{date_prefix}_{safe_filename(title)}{archive_suffix}.md"

        if filepath.exists():
            skipped += 1
            continue

        prefix = f"[{label}] " if label else ""
        print(f"  {prefix}{title[:65]}{' [archived]' if archived else ''}")
        try:
            conv_data = fetch_json(page, token, f"/backend-api/conversation/{cid}")
            md        = to_markdown(conv_data, title, created, archived=archived)
            filepath.write_text(md, encoding="utf-8")
            saved += 1
        except Exception as e:
            print(f"    !! Error: {e}")
            errors += 1

        time.sleep(DELAY)
    return saved, skipped, errors

# ── Conversation → Markdown ───────────────────────────────────────────────────

def extract_messages(conv_data):
    mapping      = conv_data.get("mapping", {})
    current_node = conv_data.get("current_node")
    if not current_node:
        return []
    path    = []
    node_id = current_node
    while node_id:
        node = mapping.get(node_id, {})
        msg  = node.get("message")
        if msg and msg.get("content"):
            path.append(msg)
        node_id = node.get("parent")
    return list(reversed(path))

def render_message(msg):
    role    = msg.get("author", {}).get("role", "unknown")
    content = msg.get("content", {})
    parts   = content.get("parts", [])
    if role in ("system", "tool"):
        return None
    text_parts = []
    for part in parts:
        if isinstance(part, str) and part.strip():
            text_parts.append(part.strip())
        elif isinstance(part, dict):
            ctype = part.get("content_type", "")
            if ctype == "image_asset_pointer":
                text_parts.append("*[image]*")
            elif ctype == "tether_quote":
                title = part.get("title", "")
                url   = part.get("url", "")
                text_parts.append(f"*[source: [{title}]({url})]*")
    if not text_parts:
        return None
    label = "**You:**" if role == "user" else "**ChatGPT:**"
    return f"{label}\n\n" + "\n\n".join(text_parts)

def parse_date(created):
    if isinstance(created, str):
        return datetime.fromisoformat(
            created.replace("Z", "+00:00")
        ).astimezone().replace(tzinfo=None)
    return datetime.fromtimestamp(float(created))

def to_markdown(conv_data, title, created, archived=False):
    date_str = parse_date(created).strftime("%Y-%m-%d %H:%M")
    lines    = [f"# {title}", f"*{date_str}*{' | archived' if archived else ''}", ""]
    for msg in extract_messages(conv_data):
        rendered = render_message(msg)
        if rendered:
            lines.append(rendered)
            lines.append("")
            lines.append("---")
            lines.append("")
    return "\n".join(lines)

def safe_filename(title):
    slug = re.sub(r'[<>:"/\\|?*\n\r]', "", title)
    slug = slug.strip().replace(" ", "_")
    return slug[:80] or "untitled"

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        print("Opening browser...")
        context = p.chromium.launch_persistent_context(PROFILE_DIR, headless=False, channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"])
        page    = context.new_page()
        page.goto("https://chatgpt.com")
        input("\nLog in if prompted, then press Enter once your chats are visible... ")

        print("Scrolling sidebar to load all conversations...")
        scroll_sidebar(page, ticks=20)

        print("Getting auth token...")
        token        = get_token(page)
        workspace_id = get_workspace_id(page)

        # ── Regular + GPT conversations ───────────────────────────────────────
        print("Reading conversation list...")
        convos = get_all_conversations_from_api(page, token, workspace_id)
        if not convos:
            print("  API returned nothing, falling back to localStorage...")
            convos = read_convos_from_localstorage(page)

        print("Reading archived conversations...")
        archived = get_all_conversations_from_api(page, token, workspace_id, is_archived=True)
        if archived:
            existing_ids = {c["id"] for c in convos}
            for c in archived:
                if c["id"] not in existing_ids:
                    c["archived"] = True
                    convos.append(c)
            print(f"  Found {len(archived)} archived conversation(s).")

        if not convos:
            print("No conversations found.")
            context.close()
            return

        regular_convos = [c for c in convos if not c.get("gizmo_id")]
        gpt_convos     = [c for c in convos if c.get("gizmo_id")]

        print(f"\nFound {len(regular_convos)} regular, {len(gpt_convos)} GPT conversation(s).")

        total_saved = total_skipped = total_errors = 0

        if regular_convos:
            print("\nExporting regular conversations...")
            s, sk, e = save_conversations(page, token, regular_convos, OUTPUT_DIR)
            total_saved += s; total_skipped += sk; total_errors += e

        if gpt_convos:
            gpt_ids   = list({c["gizmo_id"] for c in gpt_convos})
            gpt_names = get_gpt_names(page, token, gpt_ids)
            print(f"\nExporting GPT conversations ({len(gpt_ids)} GPT(s))...")
            for gid in gpt_ids:
                name   = gpt_names.get(gid, gid)
                subset = [c for c in gpt_convos if c["gizmo_id"] == gid]
                print(f"  GPT: {name} ({len(subset)} conversation(s))")
                out = OUTPUT_DIR / "gpts" / safe_filename(name)
                s, sk, e = save_conversations(page, token, subset, out, label=name)
                total_saved += s; total_skipped += sk; total_errors += e

        # ── Project folder conversations ──────────────────────────────────────
        projects = get_projects_from_localstorage(page)
        if projects:
            print(f"\nFound {len(projects)} Project folder(s). Fetching their conversations...")
            for proj in projects:
                pid  = proj["id"]
                name = proj["name"]

                proj_convos, api_name = get_project_conversations(page, token, pid)

                if not name:
                    name = api_name or pid

                print(f"  Project: {name} ({len(proj_convos)} conversation(s))")
                out = OUTPUT_DIR / "projects" / safe_filename(name)
                s, sk, e = save_conversations(page, token, proj_convos, out, label=name)
                total_saved += s; total_skipped += sk; total_errors += e

        context.close()

    print(f"\nDone.")
    print(f"  Saved:   {total_saved}")
    print(f"  Skipped: {total_skipped} (already existed)")
    print(f"  Errors:  {total_errors}")
    print(f"  Output:  {OUTPUT_DIR.resolve()}/")


if __name__ == "__main__":
    main()
