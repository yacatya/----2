import os
import json
from datetime import datetime


def append_sale(email, utm, amount):
    """Записать продажу в Google Sheets. Возвращает True при успехе."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2.service_account import Credentials

        creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON', '')
        sheet_id = os.environ.get('GOOGLE_SHEET_ID', '')

        if not creds_json or not sheet_id:
            print("Google Sheets: GOOGLE_CREDENTIALS_JSON or GOOGLE_SHEET_ID not set")
            return False

        creds_data = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            creds_data,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )

        service = build('sheets', 'v4', credentials=creds, cache_discovery=False)

        date = datetime.now().strftime('%d.%m.%Y %H:%M')
        blogger = utm if (utm and utm != 'direct') else 'direct'
        commission = round(float(amount) * 0.3, 2)

        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range='Продажи!A:F',
            valueInputOption='USER_ENTERED',
            body={'values': [[date, email, utm, blogger, float(amount), commission]]}
        ).execute()

        return True

    except Exception as e:
        print(f"Google Sheets error: {e}")
        return False
