"""Real cloud-mode end-to-end authorization harness.

Boots the gateway as a live uvicorn subprocess in SP_DEPLOYMENT_MODE=cloud against
a throwaway Postgres database, with a local HTTPS JWKS server standing in for
Clerk, and exercises the authorization matrix over real HTTP.
"""
