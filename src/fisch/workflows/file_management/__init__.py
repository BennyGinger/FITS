"""Run-wide migration, path/tag updates and explicit processing actions.

Import the public functions from ``api``. Relocation is shared; numerical work
is isolated in ``rebuild`` and is never implicit in migration.

``relocation`` owns folder/table updates, ``transactions`` owns rollback, and
``snapshots``/``history`` own retention and restoration of previous results.
"""

from __future__ import annotations
