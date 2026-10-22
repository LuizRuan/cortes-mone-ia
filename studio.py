"""Cortes Studio: API, worker and compiled React frontend on one port."""
import os

from dotenv import load_dotenv

load_dotenv()

from cortes.studio_api import create_app

app = create_app()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=os.environ.get('GRADIO_SERVER_NAME', '127.0.0.1'),
                port=int(os.environ.get('GRADIO_SERVER_PORT', '7860')))
