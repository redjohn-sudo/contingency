"""Per-request progress from completed backend operations; no simulated model steps."""
from contextvars import ContextVar

listener = ContextVar('analysis_progress', default=None)

def report(stage, documents):
    callback = listener.get()
    if callback:
        callback({'stage': stage, 'documents': [
            {'name': doc.get('nom', 'Document'), 'lines': len(doc['texte'].splitlines())}
            for doc in documents]})
