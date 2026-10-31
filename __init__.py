"""Hermes registration for the standalone model-switch-notify plugin.

Hermes loads this package with a real ``__package__``, so the relative import
inside :func:`register` resolves at registration time. Keeping the import
inside the function also lets ``import model_switch_notify`` work from pytest
without a package context.
"""


def register(ctx) -> None:
    from .model_switch_notify import register as _register

    _register(ctx)
