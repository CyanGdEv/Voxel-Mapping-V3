"""Locate optional bundled OCR/PDF helpers inside a frozen desktop build."""
import os
from pathlib import Path
import sys

root=Path(getattr(sys,'_MEIPASS',Path(sys.executable).parent))
folders=[root/'tools'/'tesseract',root/'tools'/'poppler'/'Library'/'bin',root/'tools'/'poppler'/'bin']
existing=[str(folder) for folder in folders if folder.is_dir()]
if existing:os.environ['PATH']=os.pathsep.join(existing+[os.environ.get('PATH','')])
tessdata=root/'tools'/'tesseract'/'tessdata'
if tessdata.is_dir() and not os.environ.get('TESSDATA_PREFIX'):os.environ['TESSDATA_PREFIX']=str(tessdata)
