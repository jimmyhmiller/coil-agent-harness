# Talking to a run

A run used to be something you started and then watched. The only thing you could do
to one was cancel it: if an agent was heading somewhere wrong, or you thought of
something halfway through, there was nowhere to put that.

Every run now has an inbox.

```sh
./harness say factory-issues-1787199382644 "stop rewriting the tests, just fix the arity"
```

The agent picks it up at its next turn — after the tool call in flight, before the next
model request — and the journal records both the message and what the agent did about
it.

## What it is

A file of one JSON object per line at `$HARNESS_INBOX_DIR/<run-id>.jsonl`, defaulting
to `.factory-inbox` under the working directory:

```json
{"version":1,"text":"stop rewriting the tests, just fix the arity"}
```

A file rather than a socket, because the thing being talked to is a separate process
that may have been started by a terminal, a window, or a cron job, and all three can
append a line. Appends are `O_APPEND`, so no writer coordinates with the reader or with
another writer, and a half-written line waits for the rest instead of arriving in two
pieces.

The run id is the one in the journal — for a factory, the `run_id` of its
`factory.run.created` record. Every worker of a factory reads the factory's inbox: you
are talking to the run, not to whichever step happens to hold the floor.

## What happens to it

Two things, because one is not enough:

- it is **delivered into the conversation** at that point, so it is acted on now. On a
  wire that resends the transcript it rides in the same user turn as the tool results it
  interrupted, first, before them. On a wire that continues by response id it goes in
  with that turn's input.
- it is **added to the run's instructions**, so it stays true afterwards. Without that
  an agent does the thing it was told and then drifts back to its original assignment on
  the next turn, which is worse than not listening at all.

Both are recorded: `operator.message.delivered` carries the text and where it went.

## From the window

`coil-agent-gui` shows a live run's transcript and its composer sends into that run's
inbox. What you typed appears in the transcript where you said it, because that is where
the journal has it.

## After it has finished

A finished run has nobody left to hear you: the process is gone. The window's
composer then starts the same workflow again, in the same project, with what you
said as its context and the finished run's transcript named so the agent can see
what it already did — the work is still in the workspace, so it picks up rather
than starting over. From a terminal that is:

```sh
./harness factory run factories/two-pass --project snake --context notes.md
```

`--context` rather than a bare path, because a bare path after the folder is the
workspace.

## What it is not

It is not an interrupt. A message lands at the next turn boundary, so if the model has
just queued ten tool calls, it lands after those. There is no way to change what a model
is doing in the middle of a single turn; the honest version of "as fast as possible" is
"at the first moment the conversation can take it".
