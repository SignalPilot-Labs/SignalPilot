"""Tableau integration: the gateway owns the org PAT and every Tableau call.

Modules:

- ``urls``        parse the user-facing site URL; build browser URLs
- ``client``      REST client, one cached token per org, one re-sign-in on 401
- ``content``     search, ref resolution, workbook details/download, renders
- ``publish``     workbook and datasource publishing with credential binding
- ``connections`` SignalPilot connection -> Tableau attributes and live .tds
- ``vds``         VizQL Data Service metadata and queries
- ``service``     integration row -> client, credential verification
"""
