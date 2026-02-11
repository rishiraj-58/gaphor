"""Real-time collaboration package for Gaphor.

This package provides multi-user simultaneous diagram editing with:
- Live cursor position sharing (coloured per user, like Google Docs)
- Broadcast of every model change to all connected peers
- Operation-based conflict resolution (last-writer-wins per element
  attribute, with structural-change ordering for element
  creation/deletion)
- Clean service integration with Gaphor's EventManager / Transaction
  / UndoManager pipeline
"""
