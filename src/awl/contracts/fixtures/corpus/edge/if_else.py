"""Branch with two assignments to the same name.

From the awl-schema README. The regression it guards: both possible values
of `b` must be reachable, and the branch taken must be distinguishable from
the branch not taken.
"""

if a == 1:
    b = 1
else:
    b = "test"
