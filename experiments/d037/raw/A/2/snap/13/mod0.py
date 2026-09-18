"""Module 0 of the D-037 target."""

from d037_target.mod1 import mod1_request_handler, mod1_status_handler

MOD0_HELPER_LIMIT = 100
MOD0_BATCH_LIMIT = 100
MOD0_SESSION_LIMIT = 100


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


def h7_alpha():
    return "h7_alpha"


def h7_beta():
    return "h7_beta"


def h7_gamma():
    return "h7_gamma"


def link_11():
    return mod1_status_handler()


def h13_alpha():
    return "h13_alpha"


def h13_beta():
    return "h13_beta"


def h13_gamma():
    return "h13_gamma"
