"""Keyword and positional calls, and a call result bound to a name.

From the awl-schema README. The regression it guards: a keyword argument
and a positional argument must remain distinguishable, and the same name
must resolve to one identity whether it is written or read.
"""

x = run(a=1)
run(x)
