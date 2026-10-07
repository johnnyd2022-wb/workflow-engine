"""The biz-e admin site: a separate, internal app for platform staff.

It is not part of the customer app. It runs in its own container, has its own session
cookie and signing key, and only the people on its allow-list can sign in (with Google).
Everything it does goes through `app.admin_site.operations`, which the admin CLI uses too.
"""
