from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas = collect_data_files('media_converter')
for name in ['mcp','torch','sentence-transformers','transformers','tokenizers','qdrant-client']:
    datas += copy_metadata(name)
hidden = ['media_converter.mcp_server','media_converter.tools.document_worker',
          'media_converter.rag.reranker_worker','sentence_transformers.cross_encoder',
          'transformers.models.xlm_roberta','transformers.models.bert','sentencepiece',
          'mysql.connector','qdrant_client']
a = Analysis([str(root/'src/media_converter/tools_entry.py')],pathex=[str(root/'src')],
    binaries=[(str(Path(sys.base_prefix)/'Library/bin'/n),'.') for n in
              ['libexpat.dll','ffi.dll','libcrypto-3-x64.dll','libssl-3-x64.dll',
               'LIBBZ2.dll','liblzma.dll','sqlite3.dll']
              if (Path(sys.base_prefix)/'Library/bin'/n).exists()],
    datas=datas,hiddenimports=hidden,
    runtime_hooks=[str(root/'packaging/windows_no_wmi.py')],
    excludes=['PySide6','tkinter','matplotlib','IPython','tensorflow','torchaudio','torchvision'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='MediaConverterTools',
          console=True,debug=False,strip=False,upx=False)
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='MediaConverterTools')
