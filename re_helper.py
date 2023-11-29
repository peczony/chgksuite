#!/usr/bin/env python
# -*- coding: utf-8 -*-
import pyperclip as pcl


def proc(x):
    if x in list("[]().+?"):
        return f"\\\\{x}"
    upper = x.upper()
    lower = x.lower()
    if upper != lower:
        return f"[{upper}{lower}]"
    else:
        return x


def main():
    cnt = pcl.paste()
    new = cnt[0] + "".join(proc(x) for x in cnt[1:])
    pcl.copy(new)


if __name__ == "__main__":
    main()
