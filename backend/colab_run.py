"""Google Colab launcher for FocusFlow backend.
1) Upload repo to Colab or git clone.
2) !pip install -r backend/requirements.txt pyngrok
3) Set os.environ['TG_BOT_TOKEN'] and run this file.
"""

import os
import threading

from pyngrok import ngrok
import uvicorn

os.environ.setdefault('FF_DB_PATH', '/content/focusflow.db')


def run():
  uvicorn.run('backend.app:app', host='0.0.0.0', port=8000, reload=False)


threading.Thread(target=run, daemon=True).start()
public_url = ngrok.connect(8000).public_url
print('Backend URL:', public_url)
print('Set this URL in Mini App field "API / Colab"')
