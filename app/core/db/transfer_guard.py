"""Restrict transfer accounting writes and preserve their recorded facts."""

from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

_accounting_write = ContextVar("_site_transfer_accounting_write", default=False)


@contextmanager
def allow_transfer_accounting():
    token = _accounting_write.set(True)
    try:
        yield
    finally:
        _accounting_write.reset(token)


def _before_flush(session, _flush_context, _instances):
    from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer

    for obj in session.new | session.dirty | session.deleted:
        if not isinstance(obj, (SiteStockReceipt, SiteStockTransfer)):
            continue
        if not _accounting_write.get():
            raise ValueError("Transfer accounting requires the recorded movement service")
        if obj in session.dirty:
            mutable = {"received_quantity", "loss_quantity"} if isinstance(obj, SiteStockTransfer) else set()
            if any(attr.history.has_changes() for attr in inspect(obj).attrs if attr.key not in mutable):
                raise ValueError("Recorded transfer and receipt facts are immutable")


def register_transfer_guard():
    if not getattr(register_transfer_guard, "_registered", False):
        event.listen(Session, "before_flush", _before_flush, propagate=True)
        register_transfer_guard._registered = True
