# Coil essentials

Coil is an s-expression language. Use the installed `coil` compiler as the source of
truth and iterate from compiler output. Search documentation narrowly; never dump the
entire guide into model context.

```sh
coil guide | rg -n -A16 -B3 'TARGETED TERM'
coil namespace NAMESPACE
coil check
coil test
```

Typed parameters are parenthesized pairs: `[(name Type)]`. Mutable locals and places
use `(mut name)`, `load`, `store!`, `field`, and `index`. Arrays have a compile-time
length, for example `(array i64 128)`. Struct construction uses named fields. Sum
variants use calls such as `(Up)`.

Tests live outside the application entry, import the product module, and use `deftest`
and assertions without importing `coil.test`. `Coil.toml` does not accept a package
`version` key.

Use `write_text_file` for new files. For existing files, prefer `edit_text_file` with a
small exact unique block so edits do not resend the whole file. After a compiler or
test failure, edit the source; do not repeat unchanged discovery commands.
