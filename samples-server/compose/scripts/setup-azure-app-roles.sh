#!/bin/sh
# ──────────────────────────────────────────────────────────────────
# Azure AD (Entra ID) App Roles setup guide for Temporal authorization.
#
# This script uses the Microsoft Graph CLI (`az ad`) to:
#   1. Create App Roles on the Temporal UI app registration
#   2. Show how to assign users/groups to those roles
#
# Prerequisites:
#   - Azure CLI (`az`) installed and logged in
#   - The App Registration client ID from .env.local
#
# The Temporal server's default ClaimMapper reads the "permissions"
# claim from the JWT.  Azure AD emits App Roles in the "roles" claim
# instead, so we tell the default mapper to read "roles" via
# TEMPORAL_JWT_PERMISSIONS_CLAIM=roles (set in docker-compose.yml).
# No custom plugin or Azure claim transformation needed.
#
# ⚡ This is a GUIDE, not an automated script.
#    Review each command before running it.
# ──────────────────────────────────────────────────────────────────
set -eu

# ── Fill in from .env.local ──
APP_CLIENT_ID="${TEMPORAL_AUTH_CLIENT_ID:?Set TEMPORAL_AUTH_CLIENT_ID}"

cat <<'GUIDE'

╔══════════════════════════════════════════════════════════════════╗
║  Azure AD App Roles → Temporal Namespace Permissions             ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Default ClaimMapper expects JWT claim:                          ║
║    "permissions": ["<namespace>:<role>", ...]                    ║
║                                                                  ║
║  role = admin | writer | reader                                  ║
║  "system:admin" = full admin on all namespaces                   ║
║                                                                  ║
║  Example App Roles to create in Azure AD:                        ║
║                                                                  ║
║    Value                        → Temporal permission            ║
║    ─────────────────────────────────────────────────              ║
║    system:admin                 → Admin on all namespaces        ║
║    default:writer               → Write on "default" namespace   ║
║    default:reader               → Read on "default" namespace    ║
║    dev:writer                   → Write on "dev" namespace       ║
║    dev:reader                   → Read on "dev" namespace        ║
║    uat:reader                   → Read on "uat" namespace        ║
║    prod:reader                  → Read on "prod" namespace       ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝

GUIDE

echo "═══ Step 1: Create App Roles ═══"
echo ""
echo "Run in Azure Portal → App registrations → $APP_CLIENT_ID → App roles → Create app role"
echo ""
echo "Or via Azure CLI (az ad app update):"
echo ""

# Generate the appRoles JSON for az ad app update
cat <<EOF
az ad app update --id $APP_CLIENT_ID --app-roles '[
  {
    "allowedMemberTypes": ["User"],
    "displayName": "Temporal System Admin",
    "description": "Full admin on all Temporal namespaces",
    "isEnabled": true,
    "value": "system:admin"
  },
  {
    "allowedMemberTypes": ["User"],
    "displayName": "Default Namespace Writer",
    "description": "Start/signal/cancel workflows in default namespace",
    "isEnabled": true,
    "value": "default:writer"
  },
  {
    "allowedMemberTypes": ["User"],
    "displayName": "Default Namespace Reader",
    "description": "View workflows in default namespace",
    "isEnabled": true,
    "value": "default:reader"
  },
  {
    "allowedMemberTypes": ["User"],
    "displayName": "Dev Namespace Writer",
    "description": "Start/signal/cancel workflows in dev namespace",
    "isEnabled": true,
    "value": "dev:writer"
  },
  {
    "allowedMemberTypes": ["User"],
    "displayName": "Dev Namespace Reader",
    "description": "View workflows in dev namespace",
    "isEnabled": true,
    "value": "dev:reader"
  },
  {
    "allowedMemberTypes": ["User"],
    "displayName": "UAT Namespace Reader",
    "description": "View workflows in uat namespace",
    "isEnabled": true,
    "value": "uat:reader"
  },
  {
    "allowedMemberTypes": ["User"],
    "displayName": "Prod Namespace Reader",
    "description": "View workflows in prod namespace",
    "isEnabled": true,
    "value": "prod:reader"
  }
]'
EOF

echo ""
echo "═══ Step 2: Assign Users/Groups to Roles ═══"
echo ""
echo "Azure Portal → Enterprise applications → Temporal UI → Users and groups → Add user/group"
echo ""
echo "Or via CLI:"
echo ""

cat <<EOF
# Get the Enterprise Application (Service Principal) object ID
SP_ID=\$(az ad sp show --id $APP_CLIENT_ID --query id -o tsv)

# Get the App Role ID for "system:admin"
ROLE_ID=\$(az ad app show --id $APP_CLIENT_ID \\
  --query "appRoles[?value=='system:admin'].id" -o tsv)

# Assign a user to the role
USER_OID=\$(az ad user show --id user@example.com --query id -o tsv)

az rest --method POST \\
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/\$SP_ID/appRoleAssignments" \\
  --body "{
    \"principalId\": \"\$USER_OID\",
    \"resourceId\": \"\$SP_ID\",
    \"appRoleId\": \"\$ROLE_ID\"
  }"
EOF

echo ""
echo "═══ Step 3: Confirm 'roles' claim is in the ID token ═══"
echo ""
echo "Azure AD includes App Role assignments in the 'roles' claim of BOTH"
echo "access tokens and ID tokens by default.  Verify this by logging in"
echo "and decoding your ID token at https://jwt.ms — you should see:"
echo ""
echo "    \"roles\": [\"default:writer\"]      (or whatever you assigned)"
echo ""
echo "If 'roles' is missing from the ID token:"
echo "  • Make sure the user is assigned to an App Role (Step 2 above)"
echo "  • App registration → Manifest → check 'appRoles' is populated"
echo "  • App registration → Expose an API → set an Application ID URI"
echo "    (sometimes needed before roles are emitted)"
echo ""
echo "The Temporal server is already configured to read this claim via"
echo "TEMPORAL_JWT_PERMISSIONS_CLAIM=roles in docker-compose.yml."
echo ""
echo "═══ Step 4: Test ═══"
echo ""
echo "  1. docker compose up -d"
echo "  2. Open http://localhost:8080"
echo "  3. Click 'Azure AD' to login"
echo "  4. Verify you can see only the namespaces your roles allow"
echo ""
echo "  Decode your token at https://jwt.ms to check the claims."
echo ""
