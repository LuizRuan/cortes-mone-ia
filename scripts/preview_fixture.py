"""Isolated UI QA server with synthetic AI. Not imported by production."""
import os
import runpy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['GROQ_API_KEY'] = 'synthetic-test-only'
fixture = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tests/test_studio.py'))
import cortes.studio_worker as worker
worker.editor = fixture['Editor']
worker.transcribe = lambda *a, **kw: fixture['transcript']()
from cortes.studio_api import create_app
import uvicorn
uvicorn.run(create_app('.cache/studio-ui-qa'),host='127.0.0.1',port=7863)
