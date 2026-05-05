"""
One-time script to obtain Google OAuth2 refresh_token.

Steps:
  1. In GCP Console → APIs & Services → Credentials
     Create an "OAuth 2.0 Client ID" of type "Desktop app"
     (no org policy blocks OAuth Client IDs — only Service Account keys)
  2. Copy the Client ID and Client Secret
  3. Run:  python get_google_token.py
  4. Paste the URL into a browser, authorise with the Google account
     that has edit access to the sheet
  5. Paste the code shown in the browser back into the terminal
  6. Copy the printed values into /opt/verevery/.env on the server

Required scope: https://www.googleapis.com/auth/spreadsheets
"""

import sys
import urllib.parse
import urllib.request
import json

CLIENT_ID     = input("Client ID: ").strip()
CLIENT_SECRET = input("Client Secret: ").strip()

SCOPE    = "https://www.googleapis.com/auth/spreadsheets"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

params = {
    "client_id":     CLIENT_ID,
    "redirect_uri":  "urn:ietf:wg:oauth:2.0:oob",
    "response_type": "code",
    "scope":         SCOPE,
    "access_type":   "offline",
    "prompt":        "consent",
}
url = AUTH_URL + "?" + urllib.parse.urlencode(params)
print("\n1. Open this URL in your browser:\n")
print(url)
print()

code = input("2. Paste the authorisation code here: ").strip()

data = urllib.parse.urlencode({
    "code":          code,
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri":  "urn:ietf:wg:oauth:2.0:oob",
    "grant_type":    "authorization_code",
}).encode()

req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
with urllib.request.urlopen(req) as resp:
    tokens = json.loads(resp.read())

refresh_token = tokens.get("refresh_token")
if not refresh_token:
    print("ERROR: no refresh_token in response:", tokens)
    sys.exit(1)

print("\n--- Add to /opt/verevery/.env ---")
print(f"GOOGLE_CLIENT_ID={CLIENT_ID}")
print(f"GOOGLE_CLIENT_SECRET={CLIENT_SECRET}")
print(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
print("---------------------------------")
print("\nDone. Also share the Google Sheet with the Google account you just authorised.")
