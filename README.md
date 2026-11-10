# MyFolks for Hermes

Your people, their folks, the details that matter.

A contact book your agent can't misremember.

Ask about anyone, from anywhere Hermes works, and get back exactly what you saved, word for word, with when and where it came from. If it isn't saved, MyFolks says so. `/contacts` never calls a model, so it keeps answering when your AI is down.

```
/contacts priya allergic

Priya
is allergic to peanuts
June this year · Telegram
```

## What it does

- **Exact answers.** You get back the words you saved.
- **Receipts.** Every answer shows when and where it came from.
- **No guessing.** If it isn't saved: `Nothing saved about that.` If MyFolks is unsure, the answer is marked `not sure`.
- **The right person.** Only an exact name or nickname opens a card. A close spelling asks "Did you mean…?" and shows nothing until you choose.
- **Linked cards.** Priya links to their dog Biscuit, so `/contacts priya dog birthday` finds it.
- **Forgiving search.** Most one-letter typos and common synonyms find the right line, with no AI model.
- **Encrypted and local.** One encrypted file on your machine. No account and no cloud.
- **Yours only.** Only you, unless you change a setting. Group chats are refused.

It works alongside any Hermes memory plugin. It does a different job: exact records, not recall.

## Install

```bash
hermes plugins install myfolks
```

Hermes asks whether to enable the plugin and whether to prepare its one Python dependency, `cryptography`. A running gateway picks up `/contacts` with no restart.

## First setup and your recovery code

Run this in your own terminal:

```bash
hermes myfolks setup
```

It shows a recovery code **once**. Keep it somewhere safe. If you lose both this device and this code, your contacts are gone.

On a new device, or if the device key is lost:

```bash
hermes myfolks recover
```

## Commands

| Command | What it does |
|---|---|
| `/contacts` | Short help and how many cards you have |
| `/contacts <name>` | A person's card |
| `/contacts <name> <question>` | Find saved lines, such as `/contacts priya allergic` |
| `/contacts save <name> <text>` | Save a line. An unknown name makes a new card |
| `/contacts link <name> <relation> <name>` | Link two cards, such as `/contacts link Priya dog Biscuit` |
| `/contacts history <name>` | Every line, with exact dates, including corrected ones |
| `/contacts correct <name>` | Numbered lines to pick from |
| `/contacts correct <name> <number> <new text>` | Correct a line. The old value is kept in history |
| `/contacts undo` | Undo the last change |
| `/contacts review` | Imported contacts waiting for you to merge or keep |

Use double quotes for a full name: `/contacts save "Priya Sharma" likes tea`.

### Choose your own command

Hermes can give MyFolks a shorter name. Add this to `config.yaml`:

```yaml
quick_commands:
  keep:
    type: alias
    target: /contacts save
```

Then `/keep Priya likes mangoes` saves that line.

## Import your contacts

```bash
hermes myfolks import <file>
```

Takes vCard files (2.1, 3.0 and 4.0) and CSV exports from Google and Outlook. An exact phone or email match merges, and `/contacts undo` reverses the whole import. Anything else with a similar name waits in `/contacts review`.

Imported text is stored as data and never treated as instructions.

## The Desktop page

1. Open **Capabilities**, then **Plugins**, in Hermes Desktop.
2. Search for `myfolks` and turn on its switch.
3. **MyFolks** appears in the sidebar.

Search, read cards, follow links, save a line and work through your review list.

## Turning on AI use

AI access is **off by default**. To turn it on, go to Settings, then Plugins, then MyFolks, or set this in `config.yaml`:

```yaml
plugins:
  entries:
    myfolks:
      settings:
        ai_tool: true
```

It takes effect from your next session. Hermes can then look up only the lines that answer a request, and save a new line, telling you what it saved. **Those lines are sent to your configured model provider.** Saved text is passed as data. A close spelling of a name counts as no match.

## Sharing with someone

Sharing is off by default. Add people as `platform:sender-id:access`, separated by commas. Access is `read`, or `add` to also save lines.

```yaml
plugins:
  entries:
    myfolks:
      settings:
        shared_people: "telegram:12345:read, telegram:67890:add"
```

Or use Settings, then Plugins, then MyFolks. It works only in private chats. Remove an entry to remove the person.

If more than one person is allowed on your bot, link your own account once with `hermes myfolks pair`, then send the code it gives you to your bot in a private chat.

## Backup and restore

```bash
hermes myfolks backup <file>
hermes myfolks restore <file>
```

Backups are encrypted with a passphrase you type privately. Restoring over a store that already has contacts asks you to type `REPLACE`. MyFolks also keeps the last 7 encrypted versions of your store.

`hermes myfolks export <file>` writes an **unencrypted** copy after you type `EXPORT`. It runs only in a terminal.

## Multiple Hermes profiles

The plugin installs into the profile you name, for example `hermes -p work plugins install myfolks`. Each profile needs its own install and `hermes -p work myfolks setup`, and has its own contacts and recovery code. Contacts never cross between profiles. The Desktop page is installed once for the app.

## Advanced: Hide from chat

Hiding stops MyFolks from showing a note in chat. Anything first typed in a chat app remains there until you delete it.

On Desktop, use **Hide from chat** on any line. In the terminal, use `/contacts hide <name> <line number>` and `/contacts unhide <name> <line number>`. `/contacts undo` reverses either.

## What to know before you rely on it

- **Telegram:** bot chats aren't end-to-end encrypted, so questions and answers there pass through Telegram.
- **Exact means exactly what was saved.** MyFolks can't know a detail has gone out of date.
- **Other software on your account:** Hermes runs as you, so anything else running as you, including other enabled plugins and an unsandboxed terminal, is not fully walled off. Running Hermes's terminal in a sandbox is the strongest setup.
- **The AI file block is a safety net.** A hook blocks AI tools that directly name the store, its key, its versions or your typed history. An indirect route, such as a wildcard in a shell command, can get past it.
- **Typed history:** Hermes keeps a plain-text history of what you type in a terminal, including `/contacts` commands.
- **Lost keys:** if both the key and the recovery code are lost, the contacts are gone.

## Disclosures

- **Network:** the plugin makes no network calls. Replies sent over a messaging platform pass through that platform.
- **AI:** `/contacts` uses no model. The optional AI tool is off by default. When on, the lines it returns go to your model provider.
- **Files:** it reads and writes only its own data folder, plus files you name for import, backup, restore or export.
- **Stored credentials:** a device key, in your OS keychain when one is available, otherwise a file only your user can read, in the plugin's data folder.
- **Hooks:** it uses `pre_tool_call` to check AI tool calls for direct access to its files. Tool arguments stay on your machine.
- **Shell commands and background processes:** none.
- **Telemetry:** none.
- **Dependency:** `cryptography`, which Hermes already includes. Declaring it makes Hermes prepare its Python environment when you install.

## Test results

Run them yourself from a checkout, with a Python that has `cryptography`:

```bash
python3 tests/evidence_pack.py
```

Measured on made-up data on one Mac:

| Check | Result |
|---|---|
| Search test set | 98 of 103 correct, and no unanswerable question got a direct answer. The 5 misses are printed by the command |
| Process killed during save, 25 times | The file was always the old or the new version |
| Three processes writing at once | 120 of 120 saves kept |
| Wrong key, wrong recovery code, tampered file | Refused, file untouched |
| Non-owner, group chat, missing sender | Refused |
| Lookup at 5,000 cards and 20,000 details | 7.9 ms median, 9.2 ms slowest |
| Save at the same size | 13.2 ms median, 16.2 ms slowest |
| `hermes plugins validate` | Passed, security scan `safe` |
