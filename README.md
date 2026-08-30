# Hearth Friend

> ### Everyone deserves a friend they can tell anything to.
>
> ### We provide the software. You own the relationship.

A self-hosted runtime for a companion with a stable identity, a memory that
accumulates, and a relationship that changes over time.

She lives in a SQLite file you own, is defined by a YAML file you write, and
speaks through whichever OpenAI-compatible model you point her at.

> **Status: early.** She talks, and every message is persisted. She remembers
> nothing beyond the recent turn window and has no behaviour of her own — at this
> point she is an LLM in a costume, and reads like one.

---

## Install

Requires Python 3.10+ and an API key for any OpenAI-compatible chat endpoint.

An embedding model runs locally so that memories are never sent anywhere to be
vectorised. It downloads on first run; set `HEARTH_EMBEDDING_MODEL=off` to skip
it and fall back to keyword matching.

```bash
git clone <this repo> && cd hearth-friend
conda env create -f environment.yml
conda activate hearth
```

Without conda:

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

Then add a key:

```bash
cp .env.example .env      # put HEARTH_API_KEY=... in it
```

## Run

```bash
hearth chat
```

```
Xiaoman · deepseek-v4-flash · 0 turns so far   (/exit to leave)
>
```

You do not have to wait for her. Send as many lines as you like; she answers
once you have stopped for a moment, and her reply arrives as a run of messages
rather than one block. Her messages can land while you are still typing.

In-chat commands: `/exit`, `/quit`, `/status`.

`hearth status` shows what is in the database, including what she has been
meaning to understand and any question the guard would not let out:

```
database  data/hearth.db (schema v1)
persona   persona/example.yaml (Xiaoman)
provider  deepseek / deepseek-v4-flash
sessions  1
turns     26
```

## Persona

Who she is lives in a YAML file, not in the code. Two are included:
`persona/example.yaml` and `persona/quiet.yaml` — deliberately different people,
so you can hear the difference.

```yaml
persona:
  name: Xiaoman
  core: |                 # background, values, how she sees herself
  language_register: |    # how she talks
  traits:                 # numbers the runtime reads: warmth, volatility,
                          # curiosity, expressiveness, baseline_mood
  message_style:          # how she breaks a reply into messages, and the
                          # pauses between them
  self:                   # things that are true about her and stay true
  reads:                  # feeds she reads; without a body this is where
                          # anything she has to say comes from
  self_disclosure: |      # her stance when asked whether she is an AI
  boundaries:             # things she must never claim
    - ...
```

Copy one, edit it, and point `HEARTH_PERSONA` at your copy. Swapping the file
swaps who is talking, against the same conversation history:

```bash
HEARTH_PERSONA=persona/quiet.yaml hearth chat
```

These are the fields it reads.

## Configuration

Environment variables, or a `.env` file in the working directory. Real
environment variables always win over the file.

| Variable | Default | |
|---|---|---|
| `HEARTH_API_KEY` | — | required |
| `HEARTH_BASE_URL` | `https://api.deepseek.com` | any OpenAI-compatible endpoint |
| `HEARTH_MODEL` | `deepseek-v4-flash` | |
| `HEARTH_PROVIDER` | `deepseek` | |
| `HEARTH_PERSONA` | `persona/example.yaml` | |
| `HEARTH_DB_PATH` | `data/hearth.db` | |
| `HEARTH_CONTEXT_TURNS` | `40` | past turns replayed as context |
| `HEARTH_SETTLE_SECONDS` | `2.0` | how long she waits for you to finish |
| `HEARTH_TEMPERATURE` | `1.0` | |
| `HEARTH_EMBEDDING_MODEL` | `BAAI/bge-m3` | local; `off` falls back to keyword matching |
| `HEARTH_USER_ID` | `local` | history is keyed by this, not by persona |
| `HEARTH_REQUEST_TIMEOUT` | `60` | seconds |

## Your data

Everything is in one SQLite file plus your persona file. There is no cloud
component and nothing to export from.

To take a copy:

```bash
hearth backup ~/hearth-2026-08-29.db
```

That writes one complete, self-contained file, and is safe to run while she is
in use. Copy the persona file alongside it — it is the other half of her.

A plain `cp` of `data/hearth.db` is only complete after a clean exit. The
database runs in WAL mode, so recent writes live in `hearth.db-wal` until they
are folded back in; copying the main file mid-session can silently produce an
empty database. `hearth backup` reads through the WAL and does not have this
problem.

The `turn` table holds every message verbatim and is **append-only, enforced by
database triggers** — updates and deletes are rejected at the storage layer.
Anything derived from it is a cache that can be dropped and rebuilt by replaying
the log. Only the turn log is irreplaceable, so only the turn log is protected.

Practically: bad decisions downstream are cheap. Re-extract, re-embed, re-score,
re-run — the source material is intact.

## How it works

One process. The core is an importable library; `hearth chat` is one entry point
into it.

```
inbound message
  -> persist the user turn            (before the model is called, so nothing said is lost)
  -> read context back from the database
  -> assemble the prompt from the persona
  -> stream a reply
  -> persist the reply                (partial replies too, if interrupted)
```

Context is read out of the database rather than held in memory, so there is no
in-process conversation state to lose. Restarting resumes rather than resets.

```
hearth_friend/
├── core/         prompt assembly, conversation loop
├── providers/    ModelProvider protocol + DeepSeek
├── store/        schema, migrations, the turn log
├── persona.py    persona loading
└── cli.py
```

`pytest` runs the suite. The deterministic layer is covered; the provider is not
exercised against a live API by the tests.

## Scope

Single user, self-hosted, one process, one file. Built for its author to use
daily. No multi-tenancy, no admin console, no hosted service.

## License

[Apache 2.0](LICENSE)
