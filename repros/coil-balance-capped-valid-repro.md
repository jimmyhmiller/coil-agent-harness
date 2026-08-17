# `coil balance` capped-candidate reproducer

The adjacent `coil-balance-capped-valid-repro.coil` is a valid program with exactly
one final `)` removed. Restoring that final delimiter makes the function compile.

The continuation branch beginning with `(let [` is deliberately indented at the
wrong level, matching the edit that exposed this behavior in `src/main.coil`.

```sh
coil balance coil-balance-capped-valid-repro.coil
```

Expected today: exit 2 with `too many possible balancings to check them all`.

```sh
coil balance --no-typecheck --strict coil-balance-capped-valid-repro.coil
```

Expected today: exit 2 because indentation implies more missing closers than the
single-delimiter deficit permits.

The ordinary mode should eventually repair this safely by exhaustively adjudicating
candidates in the damaged top-level region, stopping once a second compiling reading
makes the repair ambiguous. It should not treat an arbitrary candidate-count cap as
the semantic answer.
