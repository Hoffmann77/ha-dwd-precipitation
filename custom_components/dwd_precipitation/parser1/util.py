# -*- coding: utf-8 -*-
"""
Created on Fri May 10 14:46:43 2024

@author: Bobby
"""
import datetime as dt
import importlib


class OptionalModuleStub:
    """Stub class for optional imports.

    Objects of this class are instantiated when optional modules are not
    present on the user's machine.
    This allows global imports of optional modules with the code only breaking
    when actual attributes from this module are called.
    """

    def __init__(self, name, dep=None):
        self.name = name
        self.dep = "optional"

    def __getattr__(self, name):
        link = (
            "https://docs.wradlib.org/en/stable/"
            f"installation.html#{self.dep}-dependencies"
        )
        raise AttributeError(
            f"Module '{self.name}' is not installed.\n\n"
            "You tried to access function/module/attribute "
            f"'{name}'\nfrom module '{self.name}'.\nThis module is "
            "optional right now in wradlib.\nYou need to "
            "separately install this dependency.\n"
            f"Please refer to {link}\nfor further instructions."
        )


def has_import(module):
    return not isinstance(module, OptionalModuleStub)


def import_optional(module, dep=None):
    """Allowing for lazy loading of optional wradlib modules or dependencies.

    This function removes the need to satisfy all dependencies of wradlib
    before being able to work with it.

    Parameters
    ----------
    module : str
             name of the module

    Returns
    -------
    mod : object
          if module is present, returns the module object, on ImportError
          returns an instance of `OptionalModuleStub` which will raise an
          AttributeError as soon as any attribute is accessed.

    Examples
    --------
    Trying to import a module that exists makes the module available as normal.
    You can even use an alias. You cannot use the '*' notation, or import only
    select functions, but you can simulate most of the standard import syntax
    behavior.
    >>> m = import_optional('math')
    >>> m.log10(100)
    2.0

    Trying to import a module that does not exist, does not produce
    any errors. Only when some function is used, the code triggers an error
    >>> m = import_optional('nonexistentmodule')  # noqa
    >>> m.log10(100)  #doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    AttributeError: Module 'nonexistentmodule' is not installed.
    <BLANKLINE>
    You tried to access function/module/attribute 'log10'
    from module 'nonexistentmodule'.
    This module is optional right now in wradlib.
    You need to separately install this dependency.
    Please refer to https://docs.wradlib.org/en/stable/installation.html#optional-dependencies
    for further instructions.
    """
    try:
        mod = importlib.import_module(module)
    except ImportError:
        mod = OptionalModuleStub(module, dep=dep)

    return mod


class UTC(dt.tzinfo):
    """UTC implementation for tzinfo.

    Replaces pytz.utc
    """

    def __repr__(self):
        return "<UTC>"

    def utcoffset(self, dtime):
        return dt.timedelta(0)

    def tzname(self, dtime):
        return "UTC"

    def dst(self, dtime):
        return dt.timedelta(0)
