import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
datas = collect_data_files('media_converter') + copy_metadata('mcp')
a = Analysis([str(root/'src/media_converter/frozen_entry.py')], pathex=[str(root/'src')],
    binaries=[(str(Path(sys.base_prefix)/'Library/bin'/n),'.') for n in
              ['libexpat.dll','ffi.dll','libcrypto-3-x64.dll','libssl-3-x64.dll',
               'LIBBZ2.dll','liblzma.dll','sqlite3.dll']
              if (Path(sys.base_prefix)/'Library/bin'/n).exists()],
    datas=datas, hiddenimports=['httpx', 'mcp', 'mysql.connector'],
    runtime_hooks=[str(root/'packaging/windows_no_wmi.py')],
    excludes=['torch','transformers','sentence_transformers','tokenizers','numpy','scipy',
              'sklearn','pandas','matplotlib','IPython','tkinter'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MediaConverter',
          console=False, debug=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MediaConverter')
