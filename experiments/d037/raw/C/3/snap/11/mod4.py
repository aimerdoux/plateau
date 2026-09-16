"""Module 4 of the D-037 target."""

from d037_target.echo_util import ping


def link_9():
    return ping()


def base4(x):
    return x + 4


def twice4(x):
    return 2 * base4(x)


def mod4_request_handler():
    return 7


def mod4_alt_handler():
    return 7


def h11_alpha():
    return "h11_alpha"


def h11_beta():
    return "h11_beta"


def h11_gamma():
    return "h11_gamma"


def h5_alpha():
    return "h5_alpha"


def h5_beta():
    return "h5_beta"


def h5_gamma():
    return "h5_gamma"
