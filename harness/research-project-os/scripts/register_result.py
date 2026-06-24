#!/usr/bin/env python3
from __future__ import annotations
import runpy
import sys
from pathlib import Path
script = Path(__file__).with_name('project_os.py')
sys.argv = [str(script), 'register-result'] + sys.argv[1:]
runpy.run_path(str(script), run_name='__main__')
