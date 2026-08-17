# Factory context: Working effectively in Coil

Coil is an s-expression language, not Rust, Clojure, or JavaScript. Never guess its
syntax from another language.

Read and use this cheatsheet before writing code. It covers the common factory path.
If it does not answer a specific syntax or library question, consult `coil guide` or
`coil namespace NAME` with a narrowly targeted query and bounded output. Iterate from
compiler/test diagnostics rather than repeatedly searching unchanged documentation.

```sh
coil new /tmp/coil-reference
coil namespaces
coil namespace coil.io
coil namespace coil.http.server
```

Examples of targeted source discovery:

```sh
coil namespace coil.arraylist
rg -n '^\(defn .*ArrayList|al-push!' src tests
```

Do not use an unsized `(array T)` type; Coil arrays always have a compile-time length.
For bounded game state, a fixed array plus an explicit logical length is the simplest
representation:

```lisp
(defstruct Body [(xs (array i64 128)) (ys (array i64 128)) (length i64)])

(defn contains-cell? [(xs (ptr (array i64 128)))
                       (ys (ptr (array i64 128)))
                       (length i64) (x i64) (y i64)] (-> bool)
  (let [(mut i) 0 (mut found) false]
    (loop
      (if (>= (load i) length)
          (break)
          (do
            (when (and (= (load (index xs (load i))) x)
                       (= (load (index ys (load i))) y))
              (store! found true))
            (store! i (+ (load i) 1)))))
    (load found)))

(defn example [] (-> i64)
  (let [(mut body) (zeroed Body)]
    (store! (field body length) 3)
    (store! (index (field body xs) 0) 12)
    (store! (index (field body ys) 0) 9)
    0))
```

Use named construction for structs: `(Cell :x 12 :y 9)`. Sum values are constructed
as `(Up)` rather than `Up`, and inspected with exhaustive `match`. If a native host
must call Coil, define ordinary Coil functions and expose only those callbacks with a
top-level `(export-c [function-name :as "c_symbol"])`.

Coil can also call a chosen installed native library directly, without a C wrapper:

```lisp
(cimport "/absolute/path/to/chosen_header.h" :use [NativeFunction NativeStruct])
```

Pair that with the library's pkg-config entry in `Coil.toml`:

```toml
[native-dependencies]
chosen = { pkg-config = "chosen" }
```

Discover the header and linker metadata narrowly with `pkg-config --cflags chosen` and
`pkg-config --libs chosen`. At present `cimport` must be able to resolve the header
during its own Clang pass, so use the discovered absolute header path when a bare
header name is not found. This is a mechanism, not a prescribed GUI framework: inspect
what is installed and choose an appropriate native library yourself.

On the current development machine, this direct-native vertical slice has been
compiled and launched successfully. It is an available fallback when another header's
opaque types do not survive selective `cimport`; it is not a requirement to choose
this library:

```toml
[native-dependencies]
raylib = { pkg-config = "raylib" }
```

```lisp
(cimport "/opt/homebrew/include/raylib.h"
  :use [InitWindow CloseWindow WindowShouldClose SetTargetFPS
        BeginDrawing EndDrawing ClearBackground DrawRectangle DrawText Color])

(defn native-window-proof [] (-> i64)
  (InitWindow 320 240 c"Coil native window")
  (SetTargetFPS 60)
  (let [(mut frames) 0]
    (loop
      (if (or (WindowShouldClose) (>= (load frames) 2))
          (break)
          (do
            (BeginDrawing)
            (ClearBackground (Color :r 10 :g 20 :b 30 :a 255))
            (DrawRectangle 100 80 120 80 (Color :r 50 :g 220 :b 100 :a 255))
            (DrawText c"Native Coil" 90 40 24
                      (Color :r 240 :g 245 :b 255 :a 255))
            (EndDrawing)
            (store! frames (+ (load frames) 1))))))
  (CloseWindow)
  0)
```

Use this cheatsheet first. If a required construct is absent, query only the relevant
guide section or named namespace. Avoid broad guide dumps and compiler/standard-library
inventories because their output remains in the current worker's conversation.

The basic syntax is:

```lisp
(module application)
(import "coil.io" :use *)
(defstruct Point [(x i64) (y i64)])
(defsum Direction (Up) (Down) (Left) (Right))
(defn same-point? [(a Point) (b Point)] (-> bool)
  (and (= (get a x) (get b x))
       (= (get a y) (get b y))))
(defn main [] (-> i64)
  (println "hello")
  0)
```

Every typed function parameter is a parenthesized pair inside the parameter vector:
`[(name Type) (other-name OtherType)]`. A form such as `[name Type]` is invalid.

Projects use a `Coil.toml` with an `[package]` `entry` and `source-roots`. Tests use
`(deftest name ...)` and `(assert ...)` in separate files such as
`tests/engine_test.coil`; `deftest` is a test-runner library form and is not valid in
the normal application entry module. Put `[test]` roots/suffixes in the manifest when
custom discovery is needed. Do not import `coil.test`; no such namespace exists. A
test entry imports the product module it exercises, and `coil test` injects `deftest`
and assertion support. Factory workers have a `write_text_file` tool;
use it for source changes, then iterate from compiler output instead of repeatedly
querying the same guide sections. The feedback loop is:

`[package]` does not accept a `version` key. Use only the manifest keys shown here.

```sh
coil fmt --write FILES...
coil check
coil build
coil test
```

For a native graphical application, inspect the environment narrowly, choose an
available native approach, and build the smallest windowed vertical slice first. Keep
the game engine and state transitions in Coil. Do not substitute a browser, web view,
HTML page, terminal renderer, or turn-by-turn input loop.

Always create a compiling minimal vertical slice before adding features. After a
compiler error, change code rather than repeating discovery commands.
