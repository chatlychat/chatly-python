"""Resource namespaces, one per attribute on :class:`chatly.ChatlyClient`.

Split by the API's own grouping rather than by layer, so that finding the
code behind ``client.tickets.split(...)`` is one hop.

:class:`~chatly.resources.conversation_edges.ConversationEdges` is the one
exception and not a namespace: it is a mixin
:class:`~chatly.resources.conversations.Conversations` inherits, because the
``conversations`` group outgrew one file (contract §9) while staying one
namespace in ``surface.json``.
"""

from __future__ import annotations

from ._base import JsonDict, Resource
from .ai import AI
from .billing import Billing
from .bot_routes import BotRoutes
from .bots import Bots
from .brands import Brands
from .canvas_steps import CanvasSteps
from .channels import Channels
from .contacts import Contacts
from .conversation_edges import ConversationEdges
from .conversations import Conversations
from .customer_card_endpoints import CustomerCardEndpoints
from .customer_cards import CustomerCards
from .docs_sources import DocsSources
from .email_templates import EmailTemplates
from .events import Events
from .kb import KnowledgeBase
from .knowledge_gaps import KnowledgeGaps
from .macros import Macros
from .reports import Reports
from .search import Search
from .tickets import Tickets
from .triggers import Triggers
from .visitors import Visitors
from .webhook_deliveries import Webhooks
from .workspace import Workspace

__all__ = [
    "AI",
    "Billing",
    "BotRoutes",
    "Bots",
    "Brands",
    "CanvasSteps",
    "Channels",
    "Contacts",
    "ConversationEdges",
    "Conversations",
    "CustomerCardEndpoints",
    "CustomerCards",
    "DocsSources",
    "EmailTemplates",
    "Events",
    "JsonDict",
    "KnowledgeBase",
    "KnowledgeGaps",
    "Macros",
    "Reports",
    "Resource",
    "Search",
    "Tickets",
    "Triggers",
    "Visitors",
    "Webhooks",
    "Workspace",
]
