"""Module 0 of the D-037 target."""

from d037_target.mod1 import request_handler, queue_handler

MOD0_RETRY_LIMIT = 10

MOD0_BATCH_LIMIT = 25


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
    return request_handler()


def h7_alpha():
    return "h7_alpha"


def h7_beta():
    return "h7_beta"


def h7_gamma():
    return "h7_gamma"


def link_11():
    return queue_handler()
