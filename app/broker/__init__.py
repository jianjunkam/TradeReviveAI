"""Broker integration package.

`app.broker.yahoo` speaks HTTPS to Yahoo Finance. `app.broker.fake` exists for tests only and
must never be wired into a running app: a sample price on screen is indistinguishable from
a real one, which is the whole risk this feature carries.
"""
