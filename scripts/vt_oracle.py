#!/usr/bin/env python3
"""Small executable VT screen oracle for Coil's emitted terminal vocabulary.

This intentionally models terminal cells rather than inspecting Coil's renderer
operations. Unsupported control sequences fail loudly so test coverage cannot
silently outrun the oracle.
"""

from __future__ import annotations

import codecs
import unicodedata


class VTOracle:
    def __init__(self, rows: int, columns: int) -> None:
        self.rows = rows
        self.columns = columns
        self.screen = [[" "] * columns for _ in range(rows)]
        self.scrollback: list[str] = []
        self.row = 0
        self.column = 0
        self.wrap_pending = False
        self._state = "text"
        self._csi = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("strict")

    def feed(self, data: bytes) -> None:
        for character in self._decoder.decode(data):
            self._feed_character(character)

    def _feed_character(self, character: str) -> None:
        if self._state == "escape":
            if character != "[":
                raise AssertionError(f"unsupported escape sequence ESC {character!r}")
            self._state = "csi"
            self._csi = ""
            return
        if self._state == "csi":
            if "@" <= character <= "~":
                self._execute_csi(self._csi, character)
                self._state = "text"
            else:
                self._csi += character
            return
        if character == "\x1b":
            self._state = "escape"
        elif character == "\r":
            self.column = 0
            self.wrap_pending = False
        elif character == "\n":
            self._linefeed()
        elif character in ("\b", "\t", "\x07"):
            if character == "\b":
                self.column = max(0, self.column - 1)
            elif character == "\t":
                self.column = min(self.columns - 1, ((self.column // 8) + 1) * 8)
        elif ord(character) >= 0x20:
            self._write(character)

    def _linefeed(self) -> None:
        self.wrap_pending = False
        if self.row == self.rows - 1:
            self.scrollback.append("".join(self.screen[0]).rstrip())
            self.screen.pop(0)
            self.screen.append([" "] * self.columns)
        else:
            self.row += 1

    def _write(self, character: str) -> None:
        if self.wrap_pending:
            self.column = 0
            self._linefeed()
        width = 0 if unicodedata.combining(character) else (2 if unicodedata.east_asian_width(character) in "WF" else 1)
        if width == 0:
            target = max(0, self.column - 1)
            self.screen[self.row][target] += character
            return
        self.screen[self.row][self.column] = character
        if width == 2 and self.column + 1 < self.columns:
            self.screen[self.row][self.column + 1] = ""
        next_column = self.column + width
        if next_column >= self.columns:
            self.column = self.columns - 1
            self.wrap_pending = True
        else:
            self.column = next_column

    def _execute_csi(self, parameters: str, final: str) -> None:
        private = parameters.startswith("?")
        raw = parameters[1:] if private else parameters
        values = [int(value) if value else 0 for value in raw.split(";")] if raw else [0]
        amount = values[0] or 1
        if final == "A":
            self.row = max(0, self.row - amount)
        elif final == "B":
            self.row = min(self.rows - 1, self.row + amount)
        elif final == "C":
            self.column = min(self.columns - 1, self.column + amount)
        elif final == "K":
            mode = values[0]
            if mode == 2:
                self.screen[self.row] = [" "] * self.columns
            elif mode == 0:
                self.screen[self.row][self.column :] = [" "] * (self.columns - self.column)
            else:
                raise AssertionError(f"unsupported erase-line mode {mode}")
            self.wrap_pending = False
        elif final == "J" and values[0] == 2:
            self.screen = [[" "] * self.columns for _ in range(self.rows)]
        elif final in ("H", "f"):
            self.row = max(0, min(self.rows - 1, (values[0] or 1) - 1))
            column = values[1] if len(values) > 1 else 1
            self.column = max(0, min(self.columns - 1, (column or 1) - 1))
        elif final in ("m", "h", "l"):
            pass  # Style, cursor visibility, and bracketed-paste modes do not alter cells.
        else:
            raise AssertionError(f"unsupported CSI {parameters!r}{final}")

    def visible_lines(self) -> list[str]:
        return ["".join(row).rstrip() for row in self.screen]

    def visible_text(self) -> str:
        return "\n".join(self.visible_lines())

    def transcript(self) -> str:
        return "\n".join(self.scrollback + self.visible_lines())

    def snapshot(self) -> dict[str, object]:
        return {
            "cursor": [self.row, self.column],
            "scrollback_rows": len(self.scrollback),
            "visible": self.visible_lines(),
        }
