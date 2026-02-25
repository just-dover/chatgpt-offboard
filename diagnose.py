#!/usr/bin/env python3
"""
diagnose.py: Inspect ChatGPT localStorage and API endpoints

Use this to troubleshoot what the exporter will see before you run offboard.py.
It will show you:
  • how many conversations are cached in localStorage
  • which Project folders exist (g-p-* gizmo IDs)
  • which API endpoints work for fetching project conversations

Setup:
  pip3 install playwright
  python3 -m playwright install chromium

Run:
  python3 diagnose.py
"""

import json
from playwright.sync_api import sync_playwright

PROFILE_DIR = "./browser_profile"

def get_token(page):
    return page.evaluate("""
        async () => {
            const resp = await fetch('/api/auth/session');
            if (!resp.ok) return null;
            return (await resp.json()).accessToken || null;
        }
    """)

def fetch_auth(page, token, url):
    headers = json.dumps({"Authorization": f"Bearer {token}"})
    return page.evaluate(f"""
        async () => {{
            const resp = await fetch("{url}", {{ headers: {headers} }});
            const text = await resp.text();
            try {{ return {{ status: resp.status, body: JSON.parse(text) }}; }}
            catch(e) {{ return {{ status: resp.status, body: text.slice(0, 300) }}; }}
        }}
    """)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(PROFILE_DIR, headless=False, channel="chrome",
                args=["--disable-blink-features=AutomationControlled"])
    page    = context.new_page()
    page.goto("https://chatgpt.com")
    input("\nLog in if prompted, then press Enter once your chats are visible... ")

    # Scroll sidebar to trigger lazy loading
    print("\nScrolling sidebar...")
    for _ in range(10):
        page.evaluate("""
            () => {
                const nav = document.querySelector('nav');
                if (nav) nav.scrollTop += 2000;
                else window.scrollBy(0, 2000);
            }
        """)
        page.wait_for_timeout(400)

    token        = get_token(page)
    workspace_id = page.evaluate("() => localStorage.getItem('_account') || ''")
    print(f"\nWorkspace ID: {workspace_id or '(not found; may be a personal account)'}")

    # ── Regular conversation cache ─────────────────────────────────────────────
    conv_info = page.evaluate("""
        () => {
            const key = Object.keys(localStorage).find(k => k.includes('conversation-history'));
            if (!key) return null;
            const data = JSON.parse(localStorage.getItem(key));
            const items = data?.value?.pages?.flatMap(p => p.items) || [];
            return {
                key,
                count:      items.length,
                gpt_count:  items.filter(i => i.gizmo_id && !i.gizmo_id.startsWith('g-p-')).length,
                proj_count: items.filter(i => i.gizmo_id &&  i.gizmo_id.startsWith('g-p-')).length,
                sample_ids: items.slice(0, 3).map(i => i.id),
            };
        }
    """)
    print(f"\nconversation-history localStorage cache:")
    if conv_info:
        print(f"  Total items : {conv_info['count']}")
        print(f"  Regular     : {conv_info['count'] - conv_info['gpt_count'] - conv_info['proj_count']}")
        print(f"  GPT-backed  : {conv_info['gpt_count']}")
        print(f"  Project-tagged: {conv_info['proj_count']}")
        print(f"  Sample IDs  : {conv_info['sample_ids']}")
    else:
        print("  (not found)")

    # ── Project folders ────────────────────────────────────────────────────────
    projects = page.evaluate("""
        () => {
            const key = Object.keys(localStorage).find(k => k.includes('snorlax-history'));
            if (!key) return [];
            const data = JSON.parse(localStorage.getItem(key));
            const seen = new Set();
            const out  = [];
            for (const pg of data?.value?.pages || []) {
                for (const item of pg.items || []) {
                    const gizmo = item?.gizmo?.gizmo || {};
                    const gid   = gizmo.id || '';
                    if (gid.startsWith('g-p-') && !seen.has(gid)) {
                        seen.add(gid);
                        out.push({ id: gid, name: gizmo?.display?.name || '' });
                    }
                }
            }
            return out;
        }
    """)
    print(f"\nProject folders found in snorlax-history: {len(projects)}")
    for proj in projects:
        print(f"  {proj['name'] or '(unnamed)'} → {proj['id']}")

    # ── API probe for each project ─────────────────────────────────────────────
    if projects:
        base = "https://chatgpt.com/backend-api"
        print("\nTesting conversations API for each project:")
        for proj in projects:
            pid = proj["id"]
            url = f"{base}/gizmos/{pid}/conversations?offset=0&limit=5"
            r   = fetch_auth(page, token, url)
            body = r.get("body", {})
            if isinstance(body, dict) and "items" in body:
                items = body["items"]
                print(f"  {proj['name'] or pid}: total={body.get('total')}, fetched={len(items)}")
                if items:
                    print(f"    first title: {items[0].get('title', '?')}")
            else:
                print(f"  {proj['name'] or pid}: HTTP {r.get('status')}: {str(body)[:120]}")

    context.close()
    print("\nDone.")
