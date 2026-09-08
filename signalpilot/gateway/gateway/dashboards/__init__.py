"""Published dashboards: publish from chat, team gallery, versions, refresh.

Module map:

- ``schema``      bundled JSON schema and spec validation
- ``datasets``    csv/tsv/json parsing, CSV writing, manifest ref resolution
- ``checks``      chart checks (port of the notebook-server rules)
- ``storage``     object keys and the object-storage facade
- ``store``       all database access, visibility and edit rules, slugs
- ``schedule``    next-refresh math
- ``service``     publish, restore, settings, edit chats
- ``refresh``     refresh execution in sql and agent mode
- ``scheduler``   due-refresh loop and agent-run polling
- ``serializers`` wire shapes matching ``web/lib/api/dashboards.ts``
"""
