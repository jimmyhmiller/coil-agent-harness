# Feature request: streaming response bodies in `coil.http.client`

## Summary

Add a public streaming request API to `coil.http.client`. The API should deliver
response-body bytes incrementally through a typed Coil callback while preserving the
existing client's request types, timeout behavior, TLS defaults, and transport error
model.

The current `request` function buffers the complete response body before returning.
That works for ordinary HTTP calls but prevents clients from processing server-sent
events, newline-delimited JSON, model output, downloads, and other long responses as
bytes arrive.

## Current API

`coil.http.client` currently exports:

```coil
(defn request [(a (ptr alloc/Allocator)) (req (ptr Request))]
  (-> (Result Response HttpError)))
```

`Response` owns a fully buffered body. The module's private libcurl integration
already receives body chunks through a write callback, but callers cannot supply a
consumer for those chunks.

Applications that need incremental delivery must either wait for the complete body
or duplicate the module's private curl declarations, numeric options, and cleanup
logic. The second choice leaks a transport implementation into application code and
bypasses the typed boundary that `coil.http.client` provides.

## Proposed capability

Expose a request operation that accepts a typed body consumer. One possible API is:

```coil
(defsum BodyFlow
  (Continue [])
  (Stop []))

(defstruct BodySink
  [(context (ptr i8))
   (consume (fnptr c [(ptr u8) usize (ptr i8)] BodyFlow))])

(defstruct StreamingResponse
  [(status i64)
   (headers (slice Header))])

(defn request-stream [(a (ptr alloc/Allocator))
                      (req (ptr Request))
                      (sink BodySink)]
  (-> (Result StreamingResponse HttpError)))
```

The exact names and callback ABI can follow Coil conventions. The public contract
matters more than this sketch.

## Required behavior

- Call the consumer as response bytes arrive. Do not require the complete response
  body to fit in memory.
- Preserve byte order. The API must permit arbitrary chunk boundaries, including a
  split UTF-8 scalar or protocol record.
- Keep callback data valid only for the duration of the call. Callers copy bytes they
  need to retain.
- Let the consumer stop delivery. Map a deliberate stop to a distinct result rather
  than an unexplained transport failure.
- Return HTTP status codes and response headers even for non-2xx responses. HTTP
  status remains separate from transport success.
- Apply the existing connect and total timeouts during streaming.
- Keep TLS certificate verification and redirect policy consistent with `request`.
- Clean up the native request, header list, callback state, and partial response on
  success, timeout, consumer stop, allocation failure, and transport failure.
- Document whether the callback runs synchronously on the calling thread. A first
  version can require synchronous callbacks.
- Make reentrant requests from inside the callback either supported or explicitly
  rejected.

## Ownership

The allocator passed to `request-stream` should own returned headers and error text.
The response needs a matching release operation if those values require explicit
cleanup. Body bytes remain transport-owned during each callback and do not become
part of the returned response.

The sink context belongs to the caller. `request-stream` must not retain it after the
function returns.

## Cancellation and backpressure

Consumer-directed `Stop` provides synchronous backpressure for parsers and bounded
collectors. If Coil has a standard cancellation token, the request should also accept
or compose with it so another thread can interrupt a blocked transfer.

The API should distinguish at least:

- transport failure;
- timeout or cancellation;
- consumer-requested stop;
- allocation failure.

These cases require different retry and reporting behavior in callers.

## Acceptance tests

Add deterministic tests for:

1. A response delivered across several chunks in the original byte order.
2. A protocol record split across chunk boundaries.
3. Empty and single-chunk response bodies.
4. Binary bytes, including zero bytes and malformed UTF-8.
5. Non-2xx responses with streamed bodies and available headers.
6. Consumer stop after a partial body.
7. Connect timeout and total timeout after partial delivery.
8. Connection failure before headers and disconnect after partial delivery.
9. Repeated requests under leak and descriptor checks.
10. Cleanup when the consumer stops or returns an error.

An integration test should use a local server that flushes multiple body fragments
with a delay between writes. The test must prove that the first callback runs before
the server finishes the response; feeding a buffered body through several callbacks
would not satisfy the streaming contract.

## Compatibility

Keep the existing buffered `request` API. It can remain independently implemented or
collect `request-stream` chunks into an allocator-owned body. Existing callers should
not need changes.

This feature does not require exposing libcurl types, option numbers, or callbacks.
`coil.http.client` should continue to own those details so another transport backend
can implement the same Coil API later.

## Use case

The Coil agent harness consumes model-provider SSE responses. Incremental delivery
lets it decode events, persist durable deltas, update cancellation state, and redraw
its inline terminal footer while the provider is still generating output. With the
buffered API, the same decoder remains correct but users see no live progress until
the server closes the response.
