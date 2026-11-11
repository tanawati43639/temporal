"""Credential Pool — shared lock-pool for all processes.

Usage from any workflow::

    from automation.common.credential_pool import acquire_credential, release_credential

    cred = await acquire_credential("SAP_POOL")
    # ... use cred.username / cred.password ...
    await release_credential("SAP_POOL", cred.name)
"""

from automation.common.credential_pool.helpers import acquire_credential, release_credential

__all__ = ["acquire_credential", "release_credential"]
