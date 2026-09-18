"""Module 0 of the D-037 target."""

from d037_target.mod1 import seven_handler

MOD0_RETRY_LIMIT = 5


def link_5():
    return seven_handler()


def h1_alpha():
    return "h1_alpha"


def h1_beta():
    return "h1_beta"


def h1_gamma():
    return "h1_gamma"


def base0(x):
    return x + 0


def twice0(x):
    return 2 * base0(x)
