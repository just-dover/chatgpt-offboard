# chatgpt-offboard

Export all your ChatGPT conversations to Markdown files, including conversations inside **Project folders** and with **custom GPTs**.

Works with all ChatGPT plans: **Free, Plus, Pro, Business (formerly Team), and Enterprise**. Originally built for Business users since there's no official export feature, but useful for anyone who wants a local copy of their conversations.

## What it exports

```
exports/
  2024-03-15_How_to_center_a_div.md
  2024-04-01_Trip_planning_for_Japan.md
  ...
  gpts/
    My_Custom_GPT/
      2024-05-01_Some_conversation.md
      ...
  projects/
    Work_Project/
      2024-06-01_Some_conversation.md
      ...
```

Each file contains the full conversation in readable Markdown with timestamps. Archived conversations are exported with an `_archived` suffix in the filename and an `| archived` note in the header.

## Getting started

1. **Clone the repo**
```bash
git clone https://github.com/just-dover/chatgpt-offboard.git
cd chatgpt-offboard
```

2. **Install dependencies**
```bash
pip3 install playwright
```

> Requires **Google Chrome** to be installed on your machine (most people already have it). The script uses your real Chrome to bypass login restrictions that affect headless browsers.

3. **Run the script**
```bash
python3 offboard.py
```

A Chrome window will open. Log in to ChatGPT, wait for your conversations to load in the sidebar, then press Enter in the terminal to start the export. Conversations will be saved as Markdown files in the `exports/` folder.

Re-running is safe; files that already exist are skipped.

## Troubleshooting

If something doesn't look right (wrong conversation count, missing projects, API errors), run the diagnostic tool first:

```bash
python3 diagnose.py
```

This shows what's cached in your browser's localStorage and tests the API endpoints without downloading anything.

## How it works

ChatGPT has no public API for reading your conversation history. The internal endpoints this tool uses are unofficial and protected by Cloudflare, which fingerprints TLS connections and blocks any direct programmatic access regardless of what headers or cookies you send. The only way in is through a real browser session.

This tool uses [Playwright](https://playwright.dev/python/) to drive your system-installed Chrome, then makes API calls from inside the browser via `page.evaluate()`, which Cloudflare can't distinguish from normal user activity.

Using real Chrome (via `channel="chrome"`) also allows Google OAuth login to work. Playwright's bundled Chromium displays an "automation" badge and gets blocked by Google's sign-in; system Chrome does not.

The script also passes `--disable-blink-features=AutomationControlled`, which removes the `navigator.webdriver` browser flag that Playwright sets by default. That flag is what triggers Google's "this browser may not be secure" warning; it signals automation software, not anything actually insecure. Removing it lets Google OAuth proceed normally.

The browser profile is saved to `./browser_profile/` so you only need to log in once.

## Using a different browser

The script is set up for Chrome, but Playwright supports other browsers. If you want to use Firefox or Edge instead, change the `channel` argument in `offboard.py` and `diagnose.py`:

- **Microsoft Edge:** `channel="msedge"`
- **Firefox:** switch `p.chromium` to `p.firefox` and remove the `channel` argument

See the [Playwright docs](https://playwright.dev/python/docs/browsers) for details.

## Notes

- Your `browser_profile/` and `exports/` directories are gitignored and stay local
- Tested on Free and Business accounts; should work on Plus, Pro, and Enterprise too
- The ChatGPT API is unofficial and undocumented; it may change without notice

## License

MIT
