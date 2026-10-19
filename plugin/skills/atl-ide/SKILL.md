---
name: atl-ide
description: atl-ide: the Atelier-5 robotics IDE, a Thymio II twin in Webots over ROS 2. Validate and summarise notes (JSON objects with a title, body and tags), and read, save and delete them in the user's folder or the shared samples, from the command line, the atl-ide MCP tools or the browser page. Use when someone asks to work with atl-ide, or runs `atl-ide`. REPLACE this sample description with the tool's real triggers.
---

# atl-ide

<!--
  The template's sample skill. Rewrite it for the tool, and keep three things
  true: the frontmatter name stays "atl-ide", every `atl-ide <command>`
  line names a subcommand that exists (tests/test_core.py checks), and after
  editing, `atl-ide-skill --sync` copies this file to .claude/skills and
  plugin/skills. The packaged copy in atl/skill/ is the source.
-->

atl-ide: the Atelier-5 robotics IDE, a Thymio II twin in Webots over ROS 2.

## What a note is

A JSON object:

```json
{"title": "Kick-off", "body": "Agenda\n- scope\n- dates", "tags": ["project"]}
```

`title` is required (at most 120 characters), `body` is text, and `tags` is a
list of strings.

## Working through MCP

The `atl-ide` MCP server starts the web server if it is not running, so
you and the person at the browser work on the same files.

- `validate_note(note)` returns everything wrong with it. Run it before saving
  anything you put together by hand.
- `summarise_note(note)` gives word and line counts and the tags.
- `list_notes()`, `read_note(name, folder)`, `save_note(name, note, folder,
  base_version)`, `delete_note(name, folder)`.
- `server_url()` gives the page to hand to a person. `stop_server()` shuts it down.

## Folders

Notes live in two folders. `user` (`./mydocs`, git-ignored) holds
the person's own. `shared` holds the samples that ship with the tool. A save
with no folder goes back to where the note already lives, or to `user` when it
is new. **Always pass the `version` you read as `base_version`:** a save against
a version that has changed since then is refused (HTTP 409). Read the note again
and merge, don't overwrite.

## Without MCP

```bash
atl-ide validate note.json
atl-ide summarise note.json
```

From a checkout, without installing: `python3 -m atl.engine summarise note.json`.
The page is `./run.sh` (http://127.0.0.1:8780), or `atl-ide-web` when installed.

## Judgement

- Say what you changed and where it was saved (folder and name).
- Never delete a shared sample unless you were asked to.
