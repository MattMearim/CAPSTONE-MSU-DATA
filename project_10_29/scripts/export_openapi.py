#!/usr/bin/env python
import json
from pathlib import Path
from frib_ds.api.main import app
p=Path('docs/openapi.json')
p.write_text(json.dumps(app.openapi(),indent=2),encoding='utf-8')
print('wrote',p)
