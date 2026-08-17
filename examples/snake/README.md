# Snake in Coil

A compact, turn-based terminal Snake. Enter `w`, `a`, `s`, or `d` followed by
Enter. Eat `*`, avoid the walls and your body, and enter `q` to quit.

```sh
coil build
coil test
coil run
```

Scripted smoke test:

```sh
printf 'd\nq\n' | coil run
```
