"""Module 0 of the D-037 target."""

from d037_target.mod1 import mod1_request_handler

MOD0_HELPER_LIMIT = 100


def base0(x):
    return x + 0


def twice0(x):
    return 2 * base0(x)


def h1_alpha():
    return "h1_alpha"


def h1_beta():
    return "h1_beta"


def h1_gamma():
    return "h1_gamma"


def link_5():
    return mod1_request_handler()
