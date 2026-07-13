# -*- coding: utf-8 -*-
"""Blendit live sync - the Revit-side engine (docs/live-sync-plan.md).

DocumentChanged accumulates dirty element ids (no heavy work in the event);
Idling flushes them. Three modes: "live" (auto-flush on Idling), "trigger"
(accumulate; flush on Sync Now), "off" (unsubscribed - the default).

A flush re-extracts the dirty elements (bir_extract.delta.build_patch) and
spools a patch (transport.write_patch) that the watching Blender session
applies in ~a poll tick. Every flush also logs (output window + sync_log.txt
under the cache root) - that logging WAS the R1 spike (PATCH_ENABLED=False),
which passed 2026-07-13: clean subscribe, idempotent re-clicks ("already
subscribed - reused"), exact per-transaction flush counts, clean unsubscribe.
Set PATCH_ENABLED back to False to return to the log-only diagnostic mode.

ROCKET-MODE DISCIPLINE (the whole reason this module is shaped this way):
all cross-run state - the mode, the dirty accumulator, the subscribed
handler delegates, and the live GENERATION number - lives in pyRevit
envvars (AppDomain-wide, shared across engine recycles). Two hard-won
facts shape the lifecycle:
  1. A recycled engine re-importing this module gets NEW function objects,
     so "is anything attached?" must be answered by the envvar, never by
     module state (else every click stacks another handler).
  2. IronPython `-=` only removes a delegate from the engine that attached
     it - across recycles unsubscribe SILENTLY FAILS and old handlers stay
     attached running OLD code (E1 hit four stacked generations, the oldest
     eating every flush in log-only mode). Detach is therefore best-effort
     only; the guarantee is the GENERATION stamp: every handler checks the
     current generation and goes inert the moment it is superseded.

IronPython 2.7 / pure ASCII. Every event-handler body is fully guarded -
an exception thrown out of a Revit event handler can destabilize Revit.
"""

PATCH_ENABLED = True    # R1 spike PASSED 2026-07-13 (clean subscribe/reuse/
                        # unsubscribe, exact flush counts - see the plan doc);
                        # flushes now write real patches. A failed patch build
                        # logs + falls back to log-only for that flush.

# Bump this whenever handler/flush behaviour changes. The attached delegates
# PIN the module version that subscribed them - "already subscribed - reused"
# would happily keep running year-old code after a pyRevit reload (E1 was
# first attempted against stale log-only handlers exactly this way). A mode
# click compares the stored revision and silently swaps stale delegates for
# this engine's fresh ones.
SYNC_REV = 3

ENV_STATE = "BLENDIT_SYNC_STATE"        # "off" | "live" | "trigger"
ENV_HANDLERS = "BLENDIT_SYNC_HANDLERS"  # (doc_changed_fn, idling_fn) as attached
ENV_ACC = "BLENDIT_SYNC_ACC"            # {"dirty": set, "deleted": set, "tx": int}
ENV_OUTPUT = "BLENDIT_SYNC_OUTPUT"      # pyRevit output of the enabling command
ENV_INDEX = "BLENDIT_SYNC_INDEX"        # {element_id_str: [node, ...]} (E1)
ENV_SEQ = "BLENDIT_SYNC_SEQ"            # next patch seq int (E1)
ENV_GEN = "BLENDIT_SYNC_GEN"            # live handler generation (zombie guard)


# --- envvar plumbing ---------------------------------------------------------
def _get(name, default=None):
    try:
        from pyrevit import script
        val = script.get_envvar(name)
        return default if val is None else val
    except Exception:
        return default


def _set(name, value):
    try:
        from pyrevit import script
        script.set_envvar(name, value)
        return True
    except Exception:
        return False


def get_state():
    return _get(ENV_STATE, "off") or "off"


def _acc():
    acc = _get(ENV_ACC)
    if acc is None:
        acc = {"dirty": set(), "deleted": set(), "tx": 0}
        _set(ENV_ACC, acc)
    return acc


# --- logging (spike evidence must survive a closed output window) ------------
def _log(msg):
    line = "Blendit sync: %s" % msg
    out = _get(ENV_OUTPUT)
    if out is not None:
        try:
            out.print_md(line)
        except Exception:
            pass
    try:
        print(line)
    except Exception:
        pass
    try:
        path = _log_path()
        if path:
            import datetime
            f = open(path, "a")
            try:
                f.write("%s  %s\n" % (datetime.datetime.now().isoformat(), msg))
            finally:
                f.close()
    except Exception:
        pass


def _log_path():
    try:
        import bir_bootstrap
        import os
        root = bir_bootstrap.cache_dir_for("_sync")
        if not os.path.isdir(root):
            os.makedirs(root)
        return os.path.join(root, "sync_log.txt")
    except Exception:
        return None


# --- event handlers -----------------------------------------------------------
# NOTE: these run inside Revit's event dispatch. Never throw; never do heavy
# work in DocumentChanged (Idling is the read context for that).
#
# GENERATION STAMPING (the zombie-handler lesson): IronPython event `-=` only
# removes a delegate from the SAME engine that attached it, so across pyRevit
# engine recycles unsubscribe silently fails and handlers STACK - the E1 log
# showed "flush after 4 transaction(s)" for one edit (four generations
# attached), and the OLDEST zombie drained the accumulator with log-only code
# before the current handler ever saw it. Correctness therefore must not
# depend on detach: every attached handler captures the generation it was
# born with and goes INERT the moment the envvar generation moves past it.
def _make_handlers(gen):
    def _doc_changed(sender, args):
        try:
            if int(_get(ENV_GEN, 0) or 0) != gen:
                return   # superseded (a zombie) - inert forever
            if get_state() == "off":
                return
            acc = _acc()
            from bir_extract import _compat
            for eid in args.GetAddedElementIds():
                acc["dirty"].add(_compat.id_value(eid))
            for eid in args.GetModifiedElementIds():
                acc["dirty"].add(_compat.id_value(eid))
            for eid in args.GetDeletedElementIds():
                v = _compat.id_value(eid)
                acc["deleted"].add(v)
                acc["dirty"].discard(v)  # deleted supersedes modified-in-tx
            acc["tx"] = acc.get("tx", 0) + 1
        except Exception:
            pass

    def _idling(sender, args):
        try:
            if int(_get(ENV_GEN, 0) or 0) != gen:
                return   # superseded (a zombie) - inert forever
            if get_state() != "live":
                return
            acc = _get(ENV_ACC)
            if not acc or not (acc["dirty"] or acc["deleted"]):
                return
            _flush(sender)
        except Exception:
            pass

    return _doc_changed, _idling


def _flush(uiapp):
    """Consume the accumulator. Spike mode logs; patch mode writes a delta."""
    acc = _acc()
    dirty = sorted(acc["dirty"])
    deleted = sorted(acc["deleted"])
    tx = acc.get("tx", 0)
    acc["dirty"] = set()
    acc["deleted"] = set()
    acc["tx"] = 0
    if not (dirty or deleted):
        return

    def _preview(ids):
        head = ", ".join(str(i) for i in ids[:8])
        return head + ("..." if len(ids) > 8 else "")

    _log("flush after %d transaction(s): %d dirty [%s]  %d deleted [%s]"
         % (tx, len(dirty), _preview(dirty), len(deleted), _preview(deleted)))
    if not PATCH_ENABLED:
        return

    try:
        _write_patch(uiapp, dirty, deleted)
    except Exception as exc:
        _log("PATCH FAILED (%s) - falling back to log-only for this flush" % exc)


def _write_patch(uiapp, dirty, deleted):
    """E1: dirty ids -> re-extracted meshes -> a spool patch. Runs on Idling
    (a valid API read context)."""
    import bir_export
    from bir_contract import transport
    from bir_extract import delta

    doc = uiapp.ActiveUIDocument.Document
    view = bir_export._active_view(doc)
    if view is None:
        _log("no loadable active view - skipped patch")
        return
    bundle_ref, _blend = bir_export.cached_bundle(doc, view)
    if bundle_ref is None:
        _log("view has no loaded bundle (run Load View first) - skipped patch")
        return

    index = _get(ENV_INDEX)
    if index is None:
        index = delta.load_node_index(bundle_ref)
        _set(ENV_INDEX, index)

    meshes, removed = delta.build_patch(doc, view, dirty, deleted, index)
    if not meshes and not removed:
        _log("no visible geometry changed - nothing to patch")
        return
    spool = transport.patch_dir_of(bundle_ref, create=True)
    seq = _get(ENV_SEQ)
    if seq is None:
        seq = transport.next_patch_seq(spool)
    path = transport.write_patch(spool, seq, meshes, removed)
    _set(ENV_SEQ, seq + 1)
    _log("patch %d written: %d node(s) updated, %d removed"
         % (seq, len(meshes), len(removed)))


# --- subscription lifecycle -----------------------------------------------------
def subscribe(uiapp):
    """Attach a fresh handler generation exactly once. -> True if attached
    now, False if a CURRENT-revision subscription already existed (idempotent
    re-click). Stored handlers from an older SYNC_REV are superseded - after
    a pyRevit reload picks up new code, one mode click heals the
    subscription. Detach is BEST-EFFORT ONLY (IronPython `-=` fails silently
    across engine recycles); correctness comes from the generation bump,
    which turns every previously attached handler inert."""
    handlers = _get(ENV_HANDLERS)
    if handlers is not None:
        if len(handlers) >= 3 and handlers[2] == SYNC_REV:
            return False
        _log("stored handlers are from an older code revision - resubscribing")
        unsubscribe(uiapp)
    gen = int(_get(ENV_GEN, 0) or 0) + 1
    _set(ENV_GEN, gen)                 # retires every earlier generation NOW
    doc_h, idle_h = _make_handlers(gen)
    uiapp.Application.DocumentChanged += doc_h
    uiapp.Idling += idle_h
    _set(ENV_HANDLERS, (doc_h, idle_h, SYNC_REV, gen))
    return True


def unsubscribe(uiapp):
    """Retire the live generation (the guaranteed kill) and best-effort
    detach the stored delegates. -> True if a subscription existed."""
    _set(ENV_GEN, int(_get(ENV_GEN, 0) or 0) + 1)   # zombies go inert even
    handlers = _get(ENV_HANDLERS)                   # when detach fails below
    if handlers is None:
        return False
    doc_h, idle_h = handlers[0], handlers[1]
    try:
        uiapp.Application.DocumentChanged -= doc_h
    except Exception:
        pass
    try:
        uiapp.Idling -= idle_h
    except Exception:
        pass
    _set(ENV_HANDLERS, None)
    return True


def set_mode(uiapp, mode, report=None):
    """The ribbon entry point: 'live' / 'trigger' / 'off'."""
    mode = str(mode)
    try:
        from pyrevit import script
        _set(ENV_OUTPUT, script.get_output())
    except Exception:
        pass

    if mode == "off":
        detached = unsubscribe(uiapp)
        _set(ENV_STATE, "off")
        _set(ENV_INDEX, None)     # a later re-enable reseeds from the bundle
        _set(ENV_SEQ, None)
        _log("OFF (%s)" % ("unsubscribed" if detached else "was not subscribed"))
        if report:
            report("**Sync Off** - not listening. Load / Open / Render work "
                   "as always.")
        return

    fresh = subscribe(uiapp)
    _set(ENV_STATE, mode)
    _acc()   # make sure the accumulator exists
    _log("%s (%s)" % (mode.upper(),
                      "subscribed" if fresh else "already subscribed - reused"))
    if report:
        if mode == "live":
            report("**Live Sync on** - edits stream to the open Blender "
                   "session on idle.%s" % ("" if PATCH_ENABLED else
                                           " *(spike build: logging only)*"))
        else:
            report("**Trigger Sync on** - edits accumulate; push them with "
                   "**Sync Now**.%s" % ("" if PATCH_ENABLED else
                                        " *(spike build: logging only)*"))


def sync_now(uiapp, report=None):
    """Manual flush (the Trigger mode button; also works in Live)."""
    if get_state() == "off":
        _log("Sync Now clicked while OFF")
        if report:
            report("**Sync is Off** - turn on Live or Trigger Sync first.")
        return
    acc = _get(ENV_ACC)
    if not acc or not (acc["dirty"] or acc["deleted"]):
        _log("Sync Now: nothing pending")
        if report:
            report("**Nothing to sync** - no model changes since the last flush.")
        return
    _flush(uiapp)
    if report:
        report("**Synced** - pending changes flushed%s."
               % ("" if PATCH_ENABLED else " (spike build: logged only)"))
