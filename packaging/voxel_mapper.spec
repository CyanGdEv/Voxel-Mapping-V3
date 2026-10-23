# Build on Windows with: pyinstaller --noconfirm --clean packaging/voxel_mapper.spec
from pathlib import Path
import importlib.util
from importlib.metadata import PackageNotFoundError
import os

from PyInstaller.utils.hooks import collect_all,collect_submodules,copy_metadata

ROOT=Path(SPECPATH).parent
BUNDLE=Path(SPECPATH)
# Core geospatial, native Bedrock and source-PDF dependencies are bundled. The
# package's own optional neural learner uses NumPy, not an implicit GPU runtime.
packages=('voxel_mapper','amulet','amulet_nbt','leveldb','PyMCTranslate','rasterio',
          'pyproj','pyarrow','numpy','scipy','pymupdf','laspy','lazrs','PIL')
datas=[];binaries=[];hiddenimports=[]
for package in packages:
    if importlib.util.find_spec(package) is None:
        raise RuntimeError('Desktop build dependency is missing: '+package)
    data,binary,hidden=collect_all(package)
    datas.extend(data);binaries.extend(binary);hiddenimports.extend(hidden)
hiddenimports.extend(collect_submodules('voxel_mapper'))
hiddenimports.extend(collect_submodules('tkinter'))
for distribution in ('voxel-mapper','amulet-core','amulet-nbt','amulet-leveldb',
                     'PyMCTranslate','rasterio','pyproj','numpy','scipy','PyMuPDF',
                     'pyarrow','overturemaps','laspy','lazrs','Pillow','requests',
                     'beautifulsoup4','pypdf','fonttools'):
    try:datas.extend(copy_metadata(distribution))
    except PackageNotFoundError:
        # A few native wheels expose a differently normalized distribution
        # spelling. Native import smoke tests remain required after freezing.
        pass
for variable,target in [('VOXEL_DESKTOP_OCR_DIR','tools/tesseract'),('VOXEL_DESKTOP_PDF_DIR','tools/poppler')]:
    folder=os.environ.get(variable)
    if folder:
        source=Path(folder)
        if not source.is_dir():raise RuntimeError(variable+' does not name a directory')
        datas.append((str(source),target))
if (ROOT/'examples'/'desktop').is_dir():datas.append((str(ROOT/'examples'/'desktop'),'examples/desktop'))
for name in ('README.txt','LICENSES.txt'):
    datas.append((str(BUNDLE/name),'.'))
a=Analysis([str(ROOT/'scripts'/'windows_desktop_entry.py')],pathex=[str(ROOT)],
    binaries=binaries,datas=datas,hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],runtime_hooks=[str(BUNDLE/'desktop_runtime_hook.py')],
    excludes=['pytest','IPython','jupyter','notebook','torch','tensorflow','matplotlib'],
    noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='VoxelMapperV3',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=True,
    disable_windowed_traceback=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='VoxelMapperV3')
