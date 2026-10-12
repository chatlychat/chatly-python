"""Resource namespaces, one per attribute on :class:`chatly.ChatlyClient`.

Split by the API's own grouping rather than by layer, so that finding the
code behind ``client.tickets.split(...)`` is one hop.
"""

from __future__ import annotations

from ._base import JsonDict, Resource
from .billing import Billing
from .channels import Channels
from .contacts import Contacts
from .conversations import Conversations
from .events import Events
from .kb import KnowledgeBase
from .macros import Macros
from .reports import Reports
from .search import Search
from .tickets import Tickets
from .webhook_deliveries import Webhooks
from .workspace import Workspace

__all__ = [
    "Billing",
    "Channels",
    "Contacts",
    "Conversations",
    "Events",
    "JsonDict",
    "KnowledgeBase",
    "Macros",
    "Reports",
    "Resource",
    "Search",
    "Tickets",
    "Webhooks",
    "Workspace",
]
