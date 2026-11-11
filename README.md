# MyFolks for Hermes

![MyFolks for Hermes](assets/banner.png)

Your people, their folks, the details that matter.

A contact book your agent can't misremember.

## User guide

Start a chat message with **myfolks** (or /myfolks), then use plain words.

| To | Words | Example |
|---|---|---|
| Ask | any question, or just a name | `myfolks what's Priya's dog called?` |
| Save | **remember**, save, note, add, keep | `myfolks remember Priya is allergic to peanuts` |
| Fix | **fix**, change, edit, correct, update | `myfolks fix Priya` |
| Delete | **forget**, delete, remove | `myfolks forget Priya`, or one line: `myfolks forget Priya 2` |
| Undo | **undo** | `myfolks undo` |
| Connect | **link** | `myfolks link Priya dog Biscuit` |
| Bring people in | **sync**, **review** | `myfolks sync` |
| See changes | **history**, changes | `myfolks history Priya` |
| Help | **help** | `myfolks help` |

In Hermes Desktop, open MyFolks to search, add, edit, delete and undo with buttons. To show it: **Capabilities**, then **Plugins**, and switch on MyFolks.

## Where it works

Tested in Telegram, the Hermes terminal and Hermes Desktop. Other chat apps that Hermes connects to, such as WhatsApp, Discord or Slack, reach MyFolks the same way and should work, but haven't been tested yet.

## Quick start

1. Install: `hermes plugins install myfolks`
2. Set up once, in your own terminal with `hermes myfolks setup`, or on the MyFolks page in Hermes Desktop. It shows your recovery code once. Chats never show it.
3. From anywhere Hermes works, send `myfolks remember Priya is allergic to peanuts`, then `myfolks priya allergy`.

MyFolks acts on its own only when the result can't be wrong, tells you exactly what it did and how to undo it, and asks you first whenever a guess could be wrong.

Ask about anyone, from anywhere Hermes works, and get back exactly what you saved, word for word, with when and where it came from. If it isn't saved, MyFolks says so. `/contacts` never calls a model, so it keeps answering when your AI is down.

```
/contacts priya allergic

Priya
is allergic to peanuts
June this year · Telegram
```

## What it does

![Answers in a chat app](assets/phone.png)

- **Exact answers.** You get back the words you saved.
- **Receipts.** Every answer shows when and where it came from.
- **No guessing.** If it isn't saved: `Nothing saved about that.` If MyFolks is unsure, the answer is marked `not sure`.
- **The right person.** Only an exact name or nickname opens a card. A close spelling asks "Did you mean…?" and shows nothing until you choose.

  ![A close spelling asks first](assets/didyoumean.png)
- **Linked cards.** Priya links to their dog Biscuit, so `/contacts priya dog birthday` finds it.
- **Forgiving search.** Most one-letter typos and common synonyms find the right line, with no AI model.
- **Encrypted and local.** One encrypted file in your Hermes folder. No account and no cloud.
- **Yours only.** Only you, unless you change a setting. Group chats are refused.
- **Your own words.** Use /contacts, /myfolks, a [wake word](#the-wake-word) you choose with no slash, or [your own short command](#choose-your-own-command).

It works alongside any Hermes memory plugin. It does a different job: exact records, not recall.

## Install

```bash
hermes plugins install myfolks
```

Hermes asks whether to enable the plugin and whether to prepare its one Python dependency, `cryptography`. A running gateway picks up `/contacts` with no restart.

## First setup and your recovery code

Run this in your own terminal, or use the setup screen on the MyFolks page in Hermes Desktop:

```bash
hermes myfolks setup
```

Either shows a recovery code **once**. No chat ever shows it, not even the terminal chat. `/myfolks` with nothing after it shows when and from where MyFolks was set up. Keep it somewhere safe. MyFolks keeps what you save only in your Hermes folder, on the computer that runs Hermes. If you use it from a chat app like Telegram, that app also keeps a copy of the chat. Your address book is separate, and MyFolks never changes it. You need the recovery code if MyFolks stops opening, and to back up or export. It is not a copy, so also make a backup.

If MyFolks stops opening:

```bash
hermes myfolks recover
```

## Commands

![The same answers in the terminal](assets/terminal.png)

| Command | What it does |
|---|---|
| `/myfolks` | How many people you have, and how to ask |
| `/myfolks help` | What you can do, in plain words |
| `/myfolks what's Priya's dog called?` | Ask anything, or send just a name to see their card |
| `/myfolks remember Priya is allergic to peanuts` | Save a line. An unknown name makes a new card. Once you've imported or synced contacts, MyFolks asks first |
| `/myfolks fix Priya` | Numbered lines to pick from. `/myfolks fix Priya 2 <new text>` changes one, and the old text stays in history |
| `/myfolks forget Priya` | Delete a person. `/myfolks forget Priya 2` deletes one line |
| `/myfolks undo` | Undo your last change, whatever it was |
| `/myfolks link Priya dog Biscuit` | Link two cards |
| `/myfolks history Priya` | Every line, with exact dates, including changed and deleted ones |
| `/myfolks review` | Imported contacts waiting for you to merge or keep |
| `/myfolks sync` | Bring in your Google contacts, read-only. `/myfolks sync off` stops it |

Each word in the user guide works in place of the one shown, and `/contacts` works everywhere `/myfolks` does. Use double quotes for a full name: `/myfolks remember "Priya Sharma" likes tea`.

Saving needs a save word (remember, save, note, add, keep) after `/myfolks`, `/contacts` or the wake word at the start of a chat app message. Plain chat without these goes to the AI instead of MyFolks.

### Delete and undo

Delete hides a person or a line from everything and keeps it in history, so Undo can bring it back. MyFolks doesn't erase anything permanently yet.

On the Desktop page, each change you make there shows a short note with an Undo button. It undoes only that change, and only if nothing else changed since.

### Linking as you save

```
/contacts save Mel's dog's name Ollie
/contacts link Mel dog Ollie
/contacts mel dog
```

`Mel's` saves to Mel. When the saved words are exactly one of these, and the name belongs to one card or to nobody yet, MyFolks links them without asking: `dog's name Ollie`, `dog's name is Ollie`, `dog is Ollie`, `dog Ollie`. The reply says `Linked Ollie as Mel's dog. Undo: /contacts undo`. In every other case, such as a name one letter away from another card, it asks first.

### The wake word

In chat apps such as Telegram, start a message with `myfolks`:

- `myfolks remember Mel's dog's name Ollie` saves, and links Ollie as Mel's dog, because the words can't mean anything else. `save`, `keep` and `note` work too.
- `Myfolks, mel dog` looks something up.

The wake word works only at the start of a chat app message. A mention mid-sentence goes to the AI.

With Hermes's default busy setting, the wake word is how to ask in chat apps while Hermes is busy. A `/myfolks` or `/contacts` sent while Hermes is still replying interrupts Hermes's current task and gets "Use myfolks <question> while Hermes is busy." instead, because Hermes doesn't let plugin commands skip its busy handling. In the terminal and Desktop, use `/myfolks`. You can change the wake word, or turn it off, in Settings, then Plugins, then MyFolks, then Agent settings, or in `config.yaml`:

```yaml
plugins:
  entries:
    myfolks:
      settings:
        wake_word: folks
```

Leave it empty (`wake_word: ""`) to turn it off.

### Choose your own command

Hermes's `quick_commands` can add your own name for a command, with `type: alias` and a `target` such as `/contacts save`.

## Import your contacts

```bash
hermes myfolks import <file>
```

Takes vCard files (2.1, 3.0 and 4.0) and CSV exports from Google and Outlook. An exact phone or email match merges, and `/contacts undo` reverses the whole import. Anything else with a similar name waits in `/contacts review`.

Imported text is stored as data and never treated as instructions.

## Sync Google contacts

```
/myfolks sync
```

Brings in the people in your Google Contacts, read-only: names, phone numbers, emails and birthdays. `hermes myfolks sync` does the same in the terminal.

Set it up once. MyFolks uses your own Google Cloud sign-in client, and Hermes keeps the sign-in:

1. In the [Google Cloud console](https://console.cloud.google.com), create a project (**IAM & Admin** > **Create a Project**). Turn on the People API (**APIs & Services** > **Library**, then **People API** > **Enable**). Set up **Google Auth platform** for the project. Then create the client: **Google Auth platform** > **Clients** > **Create Client**, with **Application type** set to **Desktop app**. Under Audience, choose External, then Publish app so it shows In production. You don't need test users. (Left in Testing, Google signs you out every 7 days.)
2. Put its client ID and client secret in your Hermes `.env` (`~/.hermes/.env`, or your profile's own folder) as `MYFOLKS_GOOGLE_CLIENT_ID` and `MYFOLKS_GOOGLE_CLIENT_SECRET`.
3. On the computer that runs Hermes, run hermes auth add myfolks:google. Google says it hasn't verified this app, because it's your own: choose Advanced, then Go to <your app name>, and allow Contacts.
4. Send `/myfolks sync`.

The first sync turns sync on. After that, when you save or ask about someone MyFolks doesn't have yet, it checks Google first, at most every 10 minutes. Matching works like an import: an exact phone or email merges, a similar name waits in `/contacts review`, and `/contacts undo` reverses the last sync.

MyFolks never changes anything in Google, and deleting someone in Google never deletes their MyFolks card. `/myfolks sync off` stops every connection to Google. Your people stay.

## The Desktop page

1. Open **Capabilities**, then **Plugins**, in Hermes Desktop.
2. Search for `myfolks` and turn on its switch.
3. **MyFolks** appears in the sidebar.

Search, read cards, follow links, save a line and work through your review list.

![A card on the Desktop page](assets/desktop-card.png)

## Turning on AI use

AI access is **off by default**. To turn it on, go to Settings, then Plugins, then MyFolks, then Agent settings, or set this in `config.yaml`:

```yaml
plugins:
  entries:
    myfolks:
      settings:
        ai_tool: true
```

It takes effect from your next session. Hermes can then look up only the lines that answer a request, and save a new line, telling you what it saved. **Those lines are sent to your configured model provider.** Saved text is passed as data. A close spelling of a name counts as no match. With AI use on, a plain "remember…" message can save through Hermes.

## Sharing with someone

Sharing is off by default. Add people as `platform:sender-id:access`, separated by commas. Access is `read` or `add`. `read` lets someone look up people by name and nothing else: they can't browse cards, open a card by number or see history. `add` also lets them save lines.

```yaml
plugins:
  entries:
    myfolks:
      settings:
        shared_people: "telegram:12345:read, telegram:67890:add"
```

Or use Settings, then Plugins, then MyFolks, then Agent settings. It works only in private chats. Remove an entry to remove the person.

If more than one person is allowed on your bot, link your own account once with `hermes myfolks pair`, then send the code it gives you to your bot in a private chat.

## Backup and restore

MyFolks keeps what you save only in your Hermes folder, on the computer that runs Hermes. To keep it if you lose that computer, make a backup and keep the file somewhere else.

- **Only MyFolks:** `hermes myfolks backup` saves `~/myfolks-backup-<date-time>.mfbk`, locked with a passphrase you choose. Without the passphrase, the file can't be opened. Add `-o` with a file or folder to save it elsewhere. Restore it with `hermes myfolks restore <file>`. Restoring into a new setup gives you a new recovery code.
- **All of Hermes:** a full `hermes backup` includes MyFolks and, on a default Hermes install, the key that opens it. Anyone with that file can read what you saved in MyFolks, so treat it like a password. `hermes backup --quick` leaves MyFolks out. On a new device, restore it with `hermes import <file>`. If MyFolks then can't open, run `hermes myfolks recover`.

Restoring over existing contacts asks for your recovery code, then asks you to type `REPLACE`. MyFolks also keeps the last 7 encrypted versions of your store in your Hermes folder.

`hermes myfolks export <file>` writes an **unencrypted** copy after you type `EXPORT`. Export, backup, restore and pair ask for your recovery code first, typed privately, and do nothing without it.

## Multiple Hermes profiles

The plugin installs into the profile you name, for example `hermes -p work plugins install myfolks`. Each profile needs its own install and `hermes -p work myfolks setup`, and has its own contacts and recovery code. Contacts never cross between profiles. The Desktop page is installed once for the app.

## Advanced: Hide from chat

Hiding stops MyFolks from showing a note in chat. Anything first typed in a chat app remains there until you delete it.

![Hide from chat on Desktop](assets/hide-from-chat.png)

On Desktop, use **Hide from chat** on any line. In the terminal, use `/contacts hide <name> <line number>` and `/contacts unhide <name> <line number>`. `/contacts undo` reverses either.

## What to know before you rely on it

- **Chat apps:** if you use MyFolks from a chat app such as Telegram, that app also keeps a copy of the chat, MyFolks's answers included, on its own servers. Telegram bot chats also aren't end-to-end encrypted.
- **Exact means exactly what was saved.** MyFolks can't know a detail has gone out of date.
- **Other software on your account:** Hermes runs as you, so anything else running as you, including other enabled plugins and an unsandboxed terminal, is not fully walled off. Running Hermes's terminal in a sandbox is the strongest setup.
- **AI agents with terminal access:** an AI agent with unrestricted terminal access runs as you, with the same reach you have. A sandboxed terminal is the strong setup.
- **The AI file block is a safety net.** A hook blocks AI tools that directly name the store, its key, its versions or your typed history. An indirect route, such as a wildcard in a shell command, can get past it.
- **Typed history:** Hermes keeps a plain-text history of what you type in a terminal, including `/contacts` commands.
- **Lost computer or code:** lose the computer that runs Hermes without a backup, and what you saved in MyFolks is gone. Your address book isn't affected. Lose the recovery code and MyFolks keeps working here, but you can't back up, restore, export or pair.
- **Copies of your Hermes folder:** on a default Hermes install, the MyFolks key is a file next to its encrypted store, so any copy of your Hermes folder can open MyFolks. That includes a full `hermes backup`, Time Machine or other whole-computer backups, and a synced or backed-up home folder. Protect those copies like a password.

## Disclosures

- **Network:** none unless you send /myfolks sync. Then Hermes connects to Google for MyFolks, read-only: people.googleapis.com for your contacts, plus Google's sign-in addresses when you sign in and when Hermes refreshes the sign-in. MyFolks never reads or stores the Google sign-in: Hermes keeps it and attaches it only for people.googleapis.com. MyFolks never sends your notes anywhere. Replies sent over a messaging platform pass through that platform.
- **AI:** `/contacts` uses no model. The optional AI tool is off by default. When on, the lines it returns go to your model provider.
- **Files:** it reads and writes only its own data folder, plus files you name for import, backup, restore or export. It never reads the Google sign-in.
- **Stored credentials:** a device key, in a file only your user can read, in the plugin's data folder. MyFolks uses the OS keychain instead only when Python's `keyring` package is available to Hermes, which a default Hermes install doesn't include. The Google sign-in for sync is Hermes's own, kept in Hermes's `auth.json`; MyFolks never holds it.
- **Hooks:** three.
  - `pre_tool_call` checks AI tool calls for direct access to its files. Tool arguments stay on your machine.
  - `pre_gateway_dispatch` answers your own `/myfolks`, `/contacts` and wake word messages in chat apps before Hermes's session sees them, then drops them, so they never reach the AI or the transcript.
  - `pre_llm_call` stops a `/myfolks` or `/contacts` that reaches the AI while Hermes is busy, before any model request, and adds a short note for the AI when a message names MyFolks while AI use is off.

  For any other message, the two message hooks only check the text in memory. They don't open the store and log nothing.
- **Shell commands and background processes:** none.
- **Telemetry:** none.
- **Dependency:** `cryptography`, which Hermes already includes. Declaring it makes Hermes prepare its Python environment when you install.

## Test results

Run these yourself from a checkout, with a Python that has `cryptography`. Measured on made-up data on one Mac unless the row says otherwise. Tested on macOS and Linux. Windows is untested.

| Check | Result | Command |
|---|---|---|
| Search test set | 102 of 108 correct, and no unanswerable question got a direct answer. The 6 misses are printed | `python3 tests/evidence_pack.py` |
| Process killed during save, 25 times | The file was always the old or the new version | `python3 tests/evidence_pack.py` |
| Three processes writing at once | 120 of 120 saves kept | `python3 tests/evidence_pack.py` |
| Wrong key, wrong recovery code, tampered file | Refused, file untouched | `python3 tests/evidence_pack.py` |
| Non-owner, group chat, missing sender | Refused | `python3 tests/evidence_pack.py` |
| Near name | No details shown until you choose | `python3 tests/evidence_pack.py` |
| Lookup at 5,000 cards and 20,000 details | 8.3 ms median, 11.5 ms slowest | `python3 tests/benchmark.py` |
| Save at the same size | 14.5 ms median, 21.5 ms slowest | `python3 tests/benchmark.py` |
| Wake word check on each chat message | 0.38 microseconds median for an ordinary message | `python3 tests/benchmark.py` |
| Lookup while 5,000 contacts import | 1.8 ms median, 68 ms slowest | `python3 tests/benchmark.py` |
| Full test suite | 1,055 passed on macOS, and 1,054 passed on Linux in a container, where 1 test is skipped because it runs as root | `python3 -m pytest tests` |
| Plugin check | Passed, security scan `safe` | `hermes plugins validate .` |

## License

MIT. See [LICENSE](LICENSE).
