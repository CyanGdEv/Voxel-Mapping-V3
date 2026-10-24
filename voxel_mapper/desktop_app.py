"""CPU desktop application for persistent Voxel Mapper jobs and reviewed learning."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import importlib
import json
import multiprocessing
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import sys
import tempfile

from .desktop_runtime import DEFAULT_MEMORY_BUDGET_MB, MAX_MEMORY_BUDGET_MB, MIN_MEMORY_BUDGET_MB

JOB_KINDS = (
    ('World pilot from retained inputs', 'world_pilot'),
    ('Full Alton draft from retained inputs', 'alton_world'),
    ('Building batch / local previews', 'building_batch'),
    ('Reconstruction accuracy benchmark', 'reconstruction_benchmark'),
    ('Planning drawing pilot / source coverage', 'planning_source_pilot'),
    ('Web research / cited source evidence', 'web_research'),
    ('Web planning PDFs / automatic source pack', 'web_planning_pilot'),
    ('Planning collection / automatic follow-up batches', 'planning_collection'),
    ('Import reviewed training feedback', 'import_feedback'),
    ('Train neural candidate ranker', 'train_ranker'),
    ('Inspect retained evidence', 'inspect_evidence'),
    ('Reason about evidence (optional model)', 'reason'),
)


def default_data_directory():
    if os.name == 'nt':
        root = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData'/'Local'))
    else:
        root = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local'/'share'))
    return root/'VoxelMapperV3'


def initial_window_geometry(root):
    left=top=0;width=root.winfo_screenwidth();height=root.winfo_screenheight()
    if os.name=='nt':
        try:
            import ctypes
            from ctypes.wintypes import RECT
            work=RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48,0,ctypes.byref(work),0):
                left,top=work.left,work.top;width=work.right-work.left;height=work.bottom-work.top
        except (AttributeError,OSError):pass
    return f'{min(1120,max(900,width-60))}x{min(820,max(560,height-90))}{left+20:+d}{top+20:+d}'


def learning_summary(snapshot):
    """Human-readable memory and evaluation state; hashes stay in job details."""
    memory=snapshot.get('memory',{});training=snapshot.get('training',{});config=snapshot.get('config',{})
    latest=training.get('last_result') or {};status=latest.get('status','awaiting_reviewed_dataset')
    descriptions={
        'awaiting_reviewed_dataset':'Waiting for enough independently reviewed examples.',
        'training_queued':'A training run is queued in the background.',
        'checkpoint_promoted':'The candidate passed evaluation and became the active checkpoint.',
        'checkpoint_withheld':'The candidate did not pass evaluation; the previous active checkpoint is retained.',
        'learning_held':'Learning is waiting for a data or configuration issue to be resolved.',
        'retry_limit_reached':'Automatic retry limit reached. Inspect the latest job before retrying.',
    }
    lines=[
        'Reviewed training examples: '+str(memory.get('feedback_records',0)),
        'Saved source observations: '+str(memory.get('knowledge_items',0)),
        'Saved events: '+str(memory.get('events',0)),
        'Saved model checkpoints: '+str(memory.get('checkpoints',0)),
        'Active candidate-priority model: '+('evaluated checkpoint selected' if memory.get('active_model') else 'no evaluated checkpoint selected'),
        'Automatic learning: '+('On' if training.get('enabled',False) else 'Off'),
        '', 'Latest learning result: '+descriptions.get(status,str(status).replace('_',' ')),
    ]
    if status=='awaiting_reviewed_dataset':
        lines.extend([
            f"Training examples: {latest.get('training_records',0)} / 100 required",
            f"Evaluation examples: {latest.get('evaluation_records',0)} / 20 required",
            f"Independent buildings: {latest.get('training_buildings',0)} training, {latest.get('evaluation_buildings',0)} evaluation; at least 5 in each split",
            'Both accepted and rejected reviewed examples are needed in each split.',
        ])
    evaluation=latest.get('evaluation') or {};metrics=evaluation.get('candidate') or {}
    if metrics:
        lines.append('')
        if isinstance(metrics.get('brier'),(int,float)):lines.append(f"Evaluation prediction error (lower is better): {metrics['brier']:.4f}")
        precision=metrics.get('accept_precision')
        lines.append(f"High-confidence acceptance precision: {precision:.1%}" if isinstance(precision,(int,float)) else 'High-confidence acceptance precision: not enough predictions to assess')
        lines.append('High-confidence evaluation predictions: '+str(metrics.get('high_confidence_count',0)))
    reasons={
        'insufficient_independent_buildings':'More independently reviewed buildings are needed in each split.',
        'insufficient_reviewed_samples':'More reviewed training/evaluation examples are needed.',
        'no_held_out_brier_improvement':'The candidate did not improve held-out prediction error.',
        'insufficient_high_confidence_predictions':'Too few high-confidence evaluation predictions.',
        'held_out_accept_precision_below_policy':'High-confidence acceptance precision did not meet the 95% requirement.',
    }
    for reason in evaluation.get('reasons',[]):lines.append('Evaluation hold: '+reasons.get(reason,str(reason).replace('_',' ')))
    if latest.get('reason'):lines.append('Details: '+str(latest['reason']))
    lines.extend(['',f"CPU workers: {config.get('workers',2)}; heavy jobs at once: {config.get('heavy_jobs_at_once',1)}",
                  f"Observed process memory budget: {config.get('memory_budget_mb',DEFAULT_MEMORY_BUDGET_MB)} MB",
                  'Memory and checkpoints remain available after the application closes.',
                  'The neural model ranks evidence candidates; it does not certify physical geometry.'])
    return '\n'.join(lines)


def benchmark_summary(report):
    """Keep measured errors and missing cases visible alongside the raw receipt."""
    summary=report.get('summary',{});metrics=summary.get('metrics',{})
    lines=['Reconstruction accuracy: '+('synthetic example' if report.get('dataset_kind')=='synthetic' else 'supplied real reference dataset'),
        f"Cases within the supplied tolerances: {summary.get('cases_within_thresholds',0)} / {summary.get('case_count',0)}",
        f"Missing predictions: {summary.get('missing_predictions',0)}; incomplete predictions: {summary.get('incomplete_predictions',0)}"]
    for key,label,unit in [('footprint_iou','Mean footprint overlap',''),('boundary_hausdorff_m','Mean boundary distance',' m'),
                           ('height_error_m','Mean height error',' m'),('position_error_m','Mean placement error',' m')]:
        metric=metrics.get(key,{})
        value=metric.get('mean');measured=metric.get('measured_cases',0)
        lines.append(f'{label}: {value:.3f}{unit} ({measured} measured cases)' if isinstance(value,(int,float)) else label+': unassessed')
    lines.extend(['Missing geometry remains failed or unassessed. Completing measurement does not mean the reconstruction passed.',
        'Reference provenance and model lineage are declared inputs; this report does not establish independent physical correctness.'])
    return '\n'.join(lines)


def check_dependencies(require_ocr_tools=False):
    """Exercise native data resources in the frozen distribution without a GUI."""
    checks = {}
    def check(name, action):
        try:
            detail = action()
            checks[name] = {'status':'passed','detail':detail}
        except Exception as error:
            checks[name] = {'status':'failed','error':str(error)}
    def numpy_check():
        import numpy
        assert float(numpy.array([1.,2.])@numpy.array([3.,4.])) == 11.
        return numpy.__version__
    def projection_check():
        from pyproj import CRS, Transformer
        c = CRS.from_epsg(27700)
        x,y = Transformer.from_crs(4326,27700,always_xy=True).transform(-1.88,52.99)
        assert 400000 < x < 420000 and 330000 < y < 360000
        return c.name
    def raster_check():
        import numpy
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.transform import from_origin
        with MemoryFile() as memory:
            with memory.open(driver='GTiff',width=2,height=2,count=1,dtype='float32',crs='EPSG:27700',transform=from_origin(0,2,1,1)) as raster:
                raster.write(numpy.ones((1,2,2),dtype='float32'))
            with memory.open() as raster:
                assert float(raster.read(1).sum()) == 4.
        return rasterio.__version__
    def pdf_check():
        import pymupdf
        with pymupdf.open() as doc:
            page=doc.new_page(width=100,height=100)
            page.insert_text((10,30),'Voxel Mapper')
            assert page.get_pixmap().width == 100
        return pymupdf.VersionBind
    def bedrock_check():
        import amulet
        import amulet_nbt
        import leveldb
        from PyMCTranslate import new_translation_manager
        manager=new_translation_manager()
        assert manager is not None
        return str(getattr(amulet,'__version__','available'))
    def arrow_check():
        import pyarrow
        assert pyarrow.table({'x':[1,2]}).num_rows == 2
        return pyarrow.__version__
    check('numpy',numpy_check)
    check('pyproj',projection_check)
    check('rasterio',raster_check)
    check('pymupdf',pdf_check)
    check('bedrock',bedrock_check)
    check('pyarrow',arrow_check)
    check('scipy',lambda: importlib.import_module('scipy').__version__)
    check('tkinter',lambda: str(importlib.import_module('tkinter').TkVersion))
    optional=check_pdf_helpers()
    helpers_ok=all(row.get('status')=='passed' if row['available'] else not require_ocr_tools for row in optional.values())
    return {'status':'passed' if all(c['status']=='passed' for c in checks.values()) and helpers_ok else 'failed',
            'checks':checks,'optional_external_tools':optional,
            'reasoning_model_weights_bundled':False}


def check_pdf_helpers():
    """Exercise bundled executables and their data/DLLs, beyond PATH lookup."""
    import subprocess
    result={name:{'available':bool(shutil.which(name))} for name in ('tesseract','pdftotext','pdftoppm')}
    with tempfile.TemporaryDirectory(prefix='voxel-pdf-helper-smoke-') as directory:
        root=Path(directory)
        for name,row in result.items():
            if not row['available']:
                row['status']='unavailable';continue
            try:
                if name=='tesseract':
                    from PIL import Image,ImageDraw,ImageFont
                    image=Image.new('RGB',(360,90),'white')
                    ImageDraw.Draw(image).text((10,15),'VOXEL 123',fill='black',font=ImageFont.load_default(size=42))
                    image.save(root/'sample.png')
                    command=[shutil.which(name),str(root/'sample.png'),'stdout','-l','eng','--psm','7']
                    response=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=True)
                    text=response.stdout.decode('utf-8',errors='replace').strip()
                    if 'VOXEL' not in text.upper() or '123' not in text:raise ValueError('English OCR smoke did not recognize its test text')
                    row['recognized_text']=text
                else:
                    import pymupdf
                    with pymupdf.open() as document:
                        page=document.new_page(width=300,height=100);page.insert_text((10,40),'Voxel Mapper helper check',fontsize=16)
                        document.save(root/'sample.pdf')
                    if name=='pdftotext':
                        command=[shutil.which(name),str(root/'sample.pdf'),'-']
                        response=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=True)
                        if b'Voxel Mapper' not in response.stdout:raise ValueError('PDF text helper did not extract its test text')
                    else:
                        command=[shutil.which(name),'-f','1','-singlefile','-scale-to','128','-png',str(root/'sample.pdf'),str(root/'page')]
                        subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=True)
                        if not (root/'page.png').read_bytes().startswith(b'\x89PNG'):raise ValueError('PDF raster helper did not render its test page')
                row['status']='passed'
            except Exception as error:row.update(status='failed',error=str(error))
    return result


class DesktopWindow:
    """Only the Tk event thread touches widgets; runtime calls use a UI queue."""
    def __init__(self,root,data_directory,workers=2,memory_budget_mb=DEFAULT_MEMORY_BUDGET_MB):
        import tkinter as tk
        from tkinter import ttk
        from .desktop_runtime import DesktopRuntime
        self.tk=tk;self.ttk=ttk;self.root=root;self.runtime_factory=DesktopRuntime
        self.runtime=None;self.messages=Queue();self.dispatch=ThreadPoolExecutor(max_workers=1,thread_name_prefix='voxel-ui-dispatch')
        self.closed=False;self.last_snapshot={};self.poll_token=None;self.snapshot_pending=False;self.learning_pending=False
        self.review_windows=[];self.review_jobs=set();self.regeneration_jobs=set()
        style=ttk.Style(root)
        if os.name=='nt' and 'vista' in style.theme_names():style.theme_use('vista')
        elif 'clam' in style.theme_names():style.theme_use('clam')
        font_family='Segoe UI' if os.name=='nt' else 'DejaVu Sans'
        style.configure('.',font=(font_family,10))
        root.title('Voxel Mapper V3 - CPU desktop')
        root.geometry(initial_window_geometry(root));root.minsize(900,560)
        self.data_directory=tk.StringVar(value=str(Path(data_directory).expanduser().resolve()))
        self.workers=tk.IntVar(value=workers);self.memory_budget=tk.IntVar(value=memory_budget_mb)
        self.kind=tk.StringVar(value=JOB_KINDS[0][0]);self.config_path=tk.StringVar();self.automatic_learning=tk.BooleanVar(value=True)
        self.status=tk.StringVar(value='Starting persistent runtime...')
        outer=ttk.Frame(root,padding=16);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='Voxel Mapper V3',font=(font_family,20,'bold')).pack(anchor='w')
        ttk.Label(outer,text='CPU world jobs | persistent evidence memory | reviewed neural candidate learning').pack(anchor='w',pady=(0,14))
        settings=ttk.LabelFrame(outer,text='Local runtime',padding=10);settings.pack(fill='x')
        ttk.Label(settings,text='Persistent data folder').grid(row=0,column=0,sticky='w')
        ttk.Entry(settings,textvariable=self.data_directory).grid(row=0,column=1,columnspan=3,sticky='ew',padx=8)
        ttk.Button(settings,text='Browse...',command=self._browse_directory).grid(row=0,column=4)
        ttk.Label(settings,text='CPU workers').grid(row=1,column=0,sticky='w',pady=8)
        ttk.Spinbox(settings,from_=1,to=4,textvariable=self.workers,width=6).grid(row=1,column=1,sticky='w',padx=8)
        ttk.Label(settings,text='Observed worker memory budget (MB)').grid(row=1,column=2,sticky='w')
        ttk.Spinbox(settings,from_=MIN_MEMORY_BUDGET_MB,to=MAX_MEMORY_BUDGET_MB,increment=256,textvariable=self.memory_budget,width=8).grid(row=1,column=3,sticky='w',padx=8)
        ttk.Button(settings,text='Apply',command=self._apply_settings).grid(row=1,column=4)
        ttk.Label(settings,text='16 GB managed memory limit. Default: 2 CPU workers, one heavy job. Polling cancels over-budget jobs. Leave RAM for Windows and other apps.',wraplength=840).grid(row=2,column=0,columnspan=5,sticky='w')
        settings.columnconfigure(1,weight=1)
        from .desktop_area import PRESETS
        tabs=ttk.Notebook(outer);tabs.pack(fill='x',pady=12)
        area=ttk.Frame(tabs,padding=10);controls=ttk.Frame(tabs,padding=10);review=ttk.Frame(tabs,padding=10)
        web=ttk.Frame(tabs,padding=10)
        tabs.add(area,text='Generate an area');tabs.add(review,text='Review and accuracy');tabs.add(web,text='Web research');tabs.add(controls,text='Advanced jobs / learning')
        self.area_presets=PRESETS;self.area_preset=tk.StringVar(value=PRESETS[0]['label'])
        self.area_sources=tk.StringVar();self.area_download=tk.BooleanVar(value=True)
        self.area_scope=tk.StringVar(value=PRESETS[0]['scope']);self.select_when_visible=None
        self.area_picker=ttk.Combobox(area,textvariable=self.area_preset,values=[p['label'] for p in PRESETS],state='readonly',width=53)
        self.area_picker.grid(row=0,column=0,columnspan=2,sticky='ew')
        self.area_picker.bind('<<ComboboxSelected>>',self._area_changed)
        self.area_generate=ttk.Button(area,text='Generate area',command=self._submit_area)
        self.area_generate.grid(row=0,column=2,padx=(8,0))
        ttk.Label(area,text='Retained PDFs folder (optional)').grid(row=1,column=0,sticky='w',pady=(8,0))
        ttk.Entry(area,textvariable=self.area_sources).grid(row=1,column=1,sticky='ew',padx=8,pady=(8,0))
        ttk.Button(area,text='Browse...',command=self._browse_area_sources).grid(row=1,column=2,pady=(8,0))
        ttk.Checkbutton(area,text='Download missing original council PDFs (uses internet)',variable=self.area_download).grid(row=2,column=0,columnspan=3,sticky='w',pady=(8,0))
        ttk.Label(area,textvariable=self.area_scope,wraplength=980).grid(row=3,column=0,columnspan=3,sticky='w',pady=(8,0))
        area.columnconfigure(1,weight=1)
        review_buttons=ttk.Frame(review);review_buttons.grid(row=0,column=0,columnspan=3,sticky='w')
        ttk.Button(review_buttons,text='Review Wicker building',command=lambda:self._prepare_review('wicker')).pack(side='left')
        ttk.Button(review_buttons,text='Try correction demo',command=lambda:self._prepare_review('correction_demo')).pack(side='left',padx=8)
        self.review_open=ttk.Button(review_buttons,text='Open review queue...',command=self._open_review_queue);self.review_open.pack(side='left')
        ttk.Label(review,text='Compare the source drawing with local geometry. Save correction drafts or record an independently checked decision.',wraplength=980).grid(row=1,column=0,columnspan=3,sticky='w',pady=(8,0))
        self.benchmark_path=tk.StringVar()
        ttk.Entry(review,textvariable=self.benchmark_path).grid(row=2,column=0,sticky='ew',pady=(8,0))
        ttk.Button(review,text='Choose benchmark...',command=self._browse_benchmark).grid(row=2,column=1,padx=8,pady=(8,0))
        self.benchmark_run=ttk.Button(review,text='Run accuracy benchmark',command=self._submit_benchmark)
        self.benchmark_run.grid(row=2,column=2,pady=(8,0))
        ttk.Label(review,text='Benchmarks measure geometry against supplied references. The included example is synthetic; real accuracy needs independently reviewed references.',wraplength=980).grid(row=3,column=0,columnspan=3,sticky='w',pady=(8,0))
        review.columnconfigure(0,weight=1)
        from .web_evidence import DEFAULT_HOSTS
        self.web_query=tk.StringVar();self.web_urls=tk.StringVar()
        self.web_hosts=tk.StringVar(value=' '.join(DEFAULT_HOSTS));self.web_model=tk.StringVar()
        self.web_offline=tk.BooleanVar(value=False)
        self.web_application=tk.StringVar(value='SMD/2024/0136')
        for index,(label,variable) in enumerate([('Public search query',self.web_query),
                ('Source URLs (space separated)',self.web_urls),('Approved source hosts',self.web_hosts),
                ('Installed local model (optional)',self.web_model)]):
            ttk.Label(web,text=label).grid(row=index,column=0,sticky='w',pady=2)
            ttk.Entry(web,textvariable=variable).grid(row=index,column=1,sticky='ew',padx=8,pady=2)
        self.web_run=ttk.Button(web,text='Research web',command=self._submit_web)
        self.web_run.grid(row=0,column=2,sticky='ne')
        ttk.Checkbutton(web,text='Use cached sources only',variable=self.web_offline).grid(row=1,column=2,sticky='w')
        ttk.Label(web,text='Planning application reference').grid(row=4,column=0,sticky='w',pady=2)
        ttk.Entry(web,textvariable=self.web_application).grid(row=4,column=1,sticky='ew',padx=8,pady=2)
        self.web_planning_run=ttk.Button(web,text='Collect & analyse PDFs',command=lambda:self._submit_web(planning=True))
        self.web_planning_run.grid(row=4,column=2,sticky='e')
        ttk.Label(web,text='Collect planning documents with saved progress and bounded retries. Review source gaps and drawing previews in Results.',wraplength=860).grid(row=5,column=0,columnspan=3,sticky='w',pady=(6,0))
        web.columnconfigure(1,weight=1)
        ttk.Combobox(controls,textvariable=self.kind,values=[label for label,_ in JOB_KINDS],state='readonly',width=38).grid(row=0,column=0,sticky='ew')
        ttk.Entry(controls,textvariable=self.config_path).grid(row=0,column=1,sticky='ew',padx=8)
        ttk.Button(controls,text='Choose JSON...',command=self._browse_job).grid(row=0,column=2)
        ttk.Button(controls,text='Start job',command=self._submit).grid(row=0,column=3,padx=(8,0))
        ttk.Label(controls,text='Import independently reviewed outcomes to learn from mistakes. Scores and successful exports do not create training labels.',wraplength=980).grid(row=1,column=0,columnspan=4,sticky='w',pady=(8,0))
        self.learning_checkbox=ttk.Checkbutton(controls,text='Learn from reviewed feedback automatically',variable=self.automatic_learning,command=self._toggle_learning)
        self.learning_checkbox.grid(row=2,column=0,columnspan=4,sticky='w',pady=(8,0))
        controls.columnconfigure(1,weight=1)
        panes=ttk.Panedwindow(outer,orient='vertical');panes.pack(fill='both',expand=True)
        top=ttk.Frame(panes);panes.add(top,weight=3)
        columns=('id','kind','status','progress','message')
        self.jobs=ttk.Treeview(top,columns=columns,show='headings',height=9,selectmode='browse')
        for key,width in [('id',150),('kind',130),('status',100),('progress',80),('message',470)]:
            self.jobs.heading(key,text=key.replace('_',' ').title());self.jobs.column(key,width=width,stretch=key=='message')
        scroll=ttk.Scrollbar(top,orient='vertical',command=self.jobs.yview);self.jobs.configure(yscrollcommand=scroll.set)
        self.jobs.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        self.jobs.bind('<<TreeviewSelect>>',lambda event:self._show_details())
        actions=ttk.Frame(outer);actions.pack(side='bottom',before=panes,fill='x',pady=(8,0))
        cancel_button=ttk.Button(actions,text='Cancel selected job',command=self._cancel);cancel_button.pack(side='left')
        ttk.Button(actions,text='Open data folder',command=self._open_directory).pack(side='left',padx=8)
        world_button=ttk.Button(actions,text='Open world',command=lambda:self._open_job_output('park.mcworld'));world_button.pack(side='left')
        compare_button=ttk.Button(actions,text='Compare geometry',command=lambda:self._open_job_output('placement-comparison.svg'));compare_button.pack(side='left',padx=8)
        results_button=ttk.Button(actions,text='Results folder',command=self._open_job_folder);results_button.pack(side='left')
        self.primary_controls=(self.area_generate,cancel_button,world_button,compare_button,results_button)
        ttk.Label(actions,textvariable=self.status).pack(side='left',padx=8)
        bottom=ttk.Notebook(panes);panes.add(bottom,weight=2)
        memory_frame=ttk.Frame(bottom);detail_frame=ttk.Frame(bottom)
        bottom.add(memory_frame,text='Persistent memory / training');bottom.add(detail_frame,text='Advanced job details / logs')
        self.memory_text=self._text(memory_frame);self.detail_text=self._text(detail_frame)
        self._replace(self.memory_text,'No active model is assumed. Training checkpoints and evidence memory will appear here.')
        root.protocol('WM_DELETE_WINDOW',self.close)
        self._create_runtime()
        self._poll()

    def _text(self,parent):
        text=self.tk.Text(parent,wrap='word',height=10,font=('Consolas',10),state='disabled')
        scroll=self.ttk.Scrollbar(parent,orient='vertical',command=text.yview);text.configure(yscrollcommand=scroll.set)
        text.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y');return text

    @staticmethod
    def _replace(widget,value):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',value);widget.configure(state='disabled')

    def _error(self,error):
        from tkinter import messagebox
        self.status.set(str(error));messagebox.showerror('Voxel Mapper',str(error),parent=self.root)

    def _background(self,action,success,failure=None):
        def run():
            try:self.messages.put(('success',success,action()))
            except Exception as error:self.messages.put(('error',failure,str(error)))
        self.dispatch.submit(run)

    def _create_runtime(self):
        path=Path(self.data_directory.get()).expanduser().resolve();workers=int(self.workers.get());budget=int(self.memory_budget.get())
        if not 1<=workers<=4 or not MIN_MEMORY_BUDGET_MB<=budget<=MAX_MEMORY_BUDGET_MB:raise ValueError(f'Choose 1-4 CPU workers and {MIN_MEMORY_BUDGET_MB}-{MAX_MEMORY_BUDGET_MB} MB of observed worker memory.')
        self.runtime=self.runtime_factory(path,workers=workers,memory_budget_mb=budget)
        self.status.set('Ready - evidence and checkpoints persist in the data folder')

    def _apply_settings(self):
        try:
            active=[j for j in self.last_snapshot.get('jobs',[]) if j.get('status') in ('queued','running','training','cancelling')]
            if active:raise ValueError('Finish or cancel running jobs before changing runtime settings.')
            if self.runtime:self.runtime.close(wait=False)
            self._create_runtime()
        except Exception as error:self._error(error)

    def _browse_directory(self):
        from tkinter import filedialog
        folder=filedialog.askdirectory(parent=self.root,initialdir=self.data_directory.get())
        if folder:self.data_directory.set(folder)

    def _browse_job(self):
        from tkinter import filedialog
        example_root=(Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent)/'examples'/'desktop'
        path=filedialog.askopenfilename(parent=self.root,title='Choose a Voxel Mapper JSON job',initialdir=str(example_root if example_root.is_dir() else Path.cwd()),filetypes=[('JSON job','*.json'),('All files','*.*')])
        if path:self.config_path.set(path)

    def _prepare_review(self,preset):
        try:
            folder=None
            if preset=='wicker':
                from tkinter import filedialog
                folder=filedialog.askdirectory(parent=self.root,title='Choose retained planning PDFs, or cancel to prepare a review with missing sources') or None
            def queued(jid):
                self.review_jobs.add(str(jid));self.select_when_visible=str(jid)
                self.status.set('Preparing the source-linked review; the review window opens when it is ready')
            self._background(lambda:self.runtime.submit_review(preset,evidence_directory=folder),queued)
        except Exception as error:self._error(error)

    def _submit_web(self,planning=False):
        try:
            query=self.web_query.get().strip();urls=self.web_urls.get().split()
            approved=self.web_hosts.get().split();model=self.web_model.get().strip()
            offline=bool(self.web_offline.get())
            reference=self.web_application.get().strip()
            def queued(jid):
                self.select_when_visible=str(jid)
                self.status.set('Web research queued; citations and failures will appear in job details')
            def submit():
                if planning: return self.runtime.submit_web_planning(reference,query,urls,
                    allowed_hosts=approved,model=model,offline=offline,collect=True)
                return self.runtime.submit_web(query,urls,allowed_hosts=approved,model=model,offline=offline)
            self._background(submit,queued)
        except Exception as error:self._error(error)

    def _open_review_queue(self,report=None):
        try:
            from .desktop_review_ui import ReviewWindow
            if report is None:
                from tkinter import filedialog
                path=filedialog.askopenfilename(parent=self.root,title='Choose a building review queue',filetypes=[('JSON review queue','*.json')])
                if not path:return
                report={'queue_path':path}
            window=ReviewWindow(self.root,Path(self.data_directory.get()).expanduser().resolve()/'reviews',
                on_feedback=self._import_reviewed_feedback,on_regenerate=self._regenerate_review)
            self.review_windows.append(window)
            window.benchmark_path.set(report.get('benchmark_path') or '')
            window.regeneration_guidance.set(report.get('demo_instructions') or 'The regenerated candidate remains provisional until independently reviewed.')
            window.load_queue(report['queue_path'],batch_path=report.get('batch_path'),source_paths=report.get('source_paths'))
        except Exception as error:self._error(error)

    def _import_reviewed_feedback(self,path):
        self._background(lambda:self.runtime.submit_reviewed_feedback(path),
            lambda jid:self.status.set('Reviewed feedback import queued; automatic learning still requires enough independent examples'))

    def _regenerate_review(self,directory,benchmark_path=None):
        def queued(jid):
            self.regeneration_jobs.add(str(jid));self.select_when_visible=str(jid)
            self.status.set('Regenerating a new local candidate and world preview; the original is retained')
        self._background(lambda:self.runtime.submit_regeneration(directory,benchmark_path=benchmark_path),queued)

    def _browse_benchmark(self):
        from tkinter import filedialog
        example_root=(Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent)/'examples'/'desktop'
        path=filedialog.askopenfilename(parent=self.root,title='Choose an accuracy benchmark',initialdir=str(example_root),filetypes=[('JSON benchmark','*.json')])
        if path:self.benchmark_path.set(path)

    def _submit_benchmark(self):
        try:
            path=Path(self.benchmark_path.get()).expanduser().resolve()
            if not path.is_file():raise ValueError('Choose an existing accuracy benchmark JSON file')
            self._background(lambda:self.runtime.submit('reconstruction_benchmark',path),
                lambda jid:self.status.set('Accuracy benchmark queued; its measured results appear in the job results folder'))
        except Exception as error:self._error(error)

    def _area_changed(self,event=None):
        preset=next(p for p in self.area_presets if p['label']==self.area_preset.get())
        self.area_scope.set(preset['scope'])

    def _browse_area_sources(self):
        from tkinter import filedialog
        folder=filedialog.askdirectory(parent=self.root,title='Choose the folder containing retained original planning PDFs')
        if folder:self.area_sources.set(folder)

    def _submit_area(self):
        try:
            preset=next(p for p in self.area_presets if p['label']==self.area_preset.get())
            folder=self.area_sources.get().strip() or None;download=bool(self.area_download.get())
            self.area_generate.state(['disabled'])
            def queued(jid):
                self.area_generate.state(['!disabled']);self.select_when_visible=str(jid)
                self.status.set('Area generation queued; progress and outputs appear below')
            def failed(error):
                self.area_generate.state(['!disabled']);self._error(error)
            self._background(lambda:self.runtime.submit_area(preset['id'],evidence_directory=folder,download_missing=download),queued,failed)
        except Exception as error:
            self.area_generate.state(['!disabled']);self._error(error)

    def _open_job_output(self,name):
        try:
            selected=self.jobs.selection()
            row=next((j for j in self.last_snapshot.get('jobs',[]) if j['id'] in selected),None)
            if not row or row.get('status')!='completed':raise ValueError('Select a completed area or world job first.')
            if row.get('kind') not in ('area_pilot','world_pilot','alton_world','regenerate_corrections'):raise ValueError('Select a world generation job.')
            if row.get('kind')=='regenerate_corrections':
                name={'park.mcworld':'corrected-native/park.mcworld','placement-comparison.svg':'geometry-comparison.svg'}[name]
            path=Path(row['output_directory'])/name
            if not path.is_file():raise ValueError('This job did not produce '+name+'. Inspect its results for missing evidence.')
            if os.name=='nt':os.startfile(str(path))
            else:self.status.set('Output: '+str(path))
        except Exception as error:self._error(error)

    def _open_job_folder(self):
        try:
            selected=self.jobs.selection()
            row=next((j for j in self.last_snapshot.get('jobs',[]) if j['id'] in selected),None)
            if not row:raise ValueError('Select a job first.')
            path=Path(row['output_directory'])
            if not path.is_dir():path=path.parent
            if os.name=='nt':os.startfile(str(path))
            else:self.status.set('Results: '+str(path))
        except Exception as error:self._error(error)

    def _submit(self):
        try:
            path=Path(self.config_path.get()).expanduser().resolve()
            if not path.is_file():raise ValueError('Choose an existing JSON job file.')
            kind=dict(JOB_KINDS)[self.kind.get()]
            self._background(lambda:self.runtime.submit(kind,path),lambda result:self.status.set('Queued job '+str(result)))
        except Exception as error:self._error(error)

    def _cancel(self):
        selected=self.jobs.selection()
        if selected:self._background(lambda:self.runtime.cancel(selected[0]),lambda result:self.status.set('Cancellation requested' if result else 'Job is already finished'))

    def _open_directory(self):
        path=str(Path(self.data_directory.get()).expanduser().resolve())
        if os.name=='nt':os.startfile(path)
        else:self.status.set('Persistent data folder: '+path)

    def _show_details(self):
        selection=self.jobs.selection();row=next((j for j in self.last_snapshot.get('jobs',[]) if str(j.get('id')) in selection),None)
        if row:
            detail=json.dumps(row,indent=2,ensure_ascii=False,default=str)
            if len(detail)>50000:detail=detail[:50000]+'\n... Display truncated; complete results remain in the job output directory.'
            if row.get('kind')=='reconstruction_benchmark' and row.get('result'):
                detail=benchmark_summary(row['result'])+'\n\nAdvanced receipt:\n'+detail
            if row.get('kind')=='planning_source_pilot' and row.get('result'):
                counts=row['result'].get('summary',{})
                detail=(f"Planning source review pack: {counts.get('completed_pages',0)} pages inspected.\n"
                    f"Visible view captions: {counts.get('visible_view_captions',0)}; enclosed surface candidates: {counts.get('surface_candidates',0)}.\n"
                    f"Closed source outlines: {counts.get('closed_source_outlines',0)}; nominal view outlines: {counts.get('nominal_view_outlines',0)}. These require physical interpretation.\n"
                    f"Source-label enclosure hints: {counts.get('source_outline_role_hints',0)} (building-related {counts.get('building_outline_hints',0)}; path/plaza-related {counts.get('path_plaza_outline_hints',0)}).\n"
                    f"Fine component boundary hypotheses: {counts.get('component_boundary_candidates',0)}; physical building exteriors require verification.\n"
                    f"Nominal component plans: {counts.get('components_with_nominal_scale_trials',0)}; printed-size consistent: {counts.get('size_consistent_component_hypotheses',0)}; mismatched: {counts.get('size_mismatched_component_hypotheses',0)}. Physical height remains unresolved.\n"
                    f"Unassigned nominal section profiles: {counts.get('nominal_section_profile_hypotheses',0)}; plan correspondence still required.\n"
                    'Open review.html in the Results folder to inspect the drawings and remaining blockers.\n'
                    'Building reconstruction, registered paths and real accuracy remain unfinished.\n\nAdvanced receipt:\n'+detail)
            if row.get('kind')=='web_research' and row.get('result'):
                result=row['result']
                detail=(f"Web sources retained: {len(result.get('sources',[]))}; unavailable: {len(result.get('failures',[]))}.\n"
                    +result.get('summary','')+'\nWebsite claims are stored evidence; no training labels or world changes were created.\n\nAdvanced receipt:\n'+detail)
            if row.get('kind')=='web_planning_pilot' and row.get('result'):
                counts=row['result']['summary']
                detail=(f"Original web PDFs analysed: {counts['unique_originals_handed_to_analysis']}; pages completed: {counts['completed_pages']}.\n"
                    f"Visible drawing captions: {counts['visible_view_captions']}; surface candidates: {counts['surface_candidates']}.\n"
                    f"Closed source outlines: {counts.get('closed_source_outlines',0)}; nominal view outlines: {counts.get('nominal_view_outlines',0)}. These require physical interpretation.\n"
                    f"Source-label enclosure hints: {counts.get('source_outline_role_hints',0)} (building-related {counts.get('building_outline_hints',0)}; path/plaza-related {counts.get('path_plaza_outline_hints',0)}).\n"
                    f"Fine component boundary hypotheses: {counts.get('component_boundary_candidates',0)}; physical building exteriors require verification.\n"
                    f"Nominal component plans: {counts.get('components_with_nominal_scale_trials',0)}; printed-size consistent: {counts.get('size_consistent_component_hypotheses',0)}; mismatched: {counts.get('size_mismatched_component_hypotheses',0)}. Physical height remains unresolved.\n"
                    f"Unassigned nominal section profiles: {counts.get('nominal_section_profile_hypotheses',0)}; plan correspondence still required.\n"
                    'Open review.html in Results folder for original drawings, page classifications and acquisition gaps.\n'
                    'Application membership and physical geometry remain unverified; no training labels or world changes were created.\n\nAdvanced receipt:\n'+detail)
            if row.get('kind')=='planning_collection' and row.get('result'):
                result=row['result'];counts=result['summary']
                detail=(f"Saved planning batches: {counts['completed_batches']}; completed sources: {counts['completed_sources']}; unresolved: {counts['unresolved_sources']}.\n"
                    f"Originals analysed: {counts['unique_originals_handed_to_analysis']}; completed pages: {counts['completed_pages']}.\n"
                    f"Documents needing analysis review: {counts['documents_needing_analysis_review']}.\n"
                    f"Closed source outlines: {counts.get('closed_source_outlines',0)}; nominal view outlines: {counts.get('nominal_view_outlines',0)}. These require physical interpretation.\n"
                    f"Source-label enclosure hints: {counts.get('source_outline_role_hints',0)} (building-related {counts.get('building_outline_hints',0)}; path/plaza-related {counts.get('path_plaza_outline_hints',0)}).\n"
                    f"Fine component boundary hypotheses: {counts.get('component_boundary_candidates',0)}; physical building exteriors require verification.\n"
                    f"Nominal component plans: {counts.get('components_with_nominal_scale_trials',0)}; printed-size consistent: {counts.get('size_consistent_component_hypotheses',0)}; mismatched: {counts.get('size_mismatched_component_hypotheses',0)}. Physical height remains unresolved.\n"
                    f"Unassigned nominal section profiles: {counts.get('nominal_section_profile_hypotheses',0)}; plan correspondence still required.\n"
                    'Open review.html in Results folder for all batch previews and the saved document queue.\n'
                    'Starting the same request resumes verified progress. Physical reconstruction remains unverified.\n\nAdvanced receipt:\n'+detail)
            if row.get('kind')=='regenerate_corrections' and row.get('result'):
                result=row['result'];comparison=result.get('benchmark',{})
                summary='New corrected local model and native preview generated. Original geometry retained.\n'
                summary+='The corrected candidate needs an independent review; no training labels or physical placement acceptance were created.\n'
                if comparison.get('status')=='measured':
                    summary+=f"Cases within reference tolerances: {comparison['before']['cases_within_thresholds']} before, {comparison['after']['cases_within_thresholds']} after. Measurements describe continuous candidate geometry.\n"
                else:summary+='Accuracy comparison awaits an independently checked reference.\n'
                detail=summary+'\nAdvanced receipt:\n'+detail
            self._replace(self.detail_text,detail)

    def _toggle_learning(self):
        desired=bool(self.automatic_learning.get());self.learning_pending=True
        self.learning_checkbox.state(['disabled'])
        def succeeded(value):
            self.learning_pending=False;self.automatic_learning.set(bool(value));self.learning_checkbox.state(['!disabled'])
            self.status.set('Automatic reviewed-feedback learning '+('enabled' if value else 'disabled'))
        def failed(error):
            self.learning_pending=False;self.automatic_learning.set(bool(self.last_snapshot.get('training',{}).get('enabled',False)))
            self.learning_checkbox.state(['!disabled']);self._error(error)
        self._background(lambda:self.runtime.set_continuous_learning(desired),succeeded,failed)

    def _snapshot_received(self,snapshot):
        self.snapshot_pending=False;self.last_snapshot=snapshot
        rows=snapshot.get('jobs',[]);present=set(self.jobs.get_children());wanted=set()
        for row in rows:
            identifier=str(row.get('id'));wanted.add(identifier)
            progress=row.get('progress','');message=row.get('message') or row.get('error') or row.get('output_directory') or ''
            values=(identifier,row.get('kind',''),row.get('status',''),progress,str(message)[:240])
            if identifier in present:self.jobs.item(identifier,values=values)
            else:self.jobs.insert('',0,iid=identifier,values=values)
            if identifier in self.review_jobs and row.get('status') in ('completed','failed','cancelled','interrupted'):
                self.review_jobs.discard(identifier)
                if row.get('status')=='completed':self._open_review_queue(row['result'])
            if identifier in self.regeneration_jobs and row.get('status') in ('completed','failed','cancelled','interrupted'):
                self.regeneration_jobs.discard(identifier)
                if row.get('status')=='completed':self._open_review_queue(row['result'])
        for identifier in present-wanted:self.jobs.delete(identifier)
        if self.select_when_visible and self.select_when_visible in wanted:
            self.jobs.selection_set(self.select_when_visible);self.jobs.see(self.select_when_visible);self.select_when_visible=None
        if not self.learning_pending:self.automatic_learning.set(bool(snapshot.get('training',{}).get('enabled',False)))
        self._replace(self.memory_text,learning_summary(snapshot));self._show_details()

    def _snapshot_failed(self,error):
        self.snapshot_pending=False;self.status.set('Runtime status: '+str(error))

    def _poll(self):
        if self.closed:return
        while True:
            try:kind,callback,value=self.messages.get_nowait()
            except Empty:break
            if callback:callback(value)
            elif kind=='error':self._error(value)
        # SQLite access and other runtime queries never block Tk's event thread.
        if self.runtime and not self.snapshot_pending:
            self.snapshot_pending=True
            self._background(self.runtime.snapshot,self._snapshot_received,self._snapshot_failed)
        self.poll_token=self.root.after(1000,self._poll)

    def close(self):
        if self.closed:return
        self.closed=True
        if self.poll_token:self.root.after_cancel(self.poll_token)
        try:
            for window in self.review_windows:
                window.close()
            if self.runtime:self.runtime.close(wait=False)
        finally:
            self.dispatch.shutdown(wait=False,cancel_futures=True);self.root.destroy()


def launch(data_directory,workers=2,memory_budget_mb=DEFAULT_MEMORY_BUDGET_MB,smoke_output=None):
    import tkinter as tk
    root=tk.Tk();window=DesktopWindow(root,data_directory,workers,memory_budget_mb)
    result=None
    if smoke_output is not None:
        smoke_output=Path(smoke_output);smoke_output.mkdir(parents=True,exist_ok=True)
        result={'status':'passed','widgets_constructed':True,'screenshot':'unavailable','memory_budget_mb':window.memory_budget.get()}
        def finish():
            try:
                root.update_idletasks()
                for widget in window.primary_controls:
                    x=widget.winfo_rootx()-root.winfo_rootx();y=widget.winfo_rooty()-root.winfo_rooty()
                    if (not widget.winfo_ismapped() or x<0 or y<0 or x+widget.winfo_width()>root.winfo_width()
                            or y+widget.winfo_height()>root.winfo_height()):
                        raise ValueError('Primary control is hidden or clipped: '+str(widget.cget('text')))
                result['primary_controls_visible']=True
                notebook=window.web_run.master.master
                notebook.select(window.web_run.master);root.update()
                for widget in (window.web_run,window.web_planning_run):
                    x=widget.winfo_rootx()-root.winfo_rootx();y=widget.winfo_rooty()-root.winfo_rooty()
                    if (not widget.winfo_ismapped() or x<0 or y<0 or
                            x+widget.winfo_width()>root.winfo_width() or y+widget.winfo_height()>root.winfo_height()):
                        raise ValueError('Web research/planning button is hidden or clipped')
                result['web_research_control_visible']=True
                result['web_planning_control_visible']=True
                try:
                    from PIL import ImageGrab
                    box=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())
                    ImageGrab.grab(bbox=box).save(smoke_output/'desktop.png');result['screenshot']='desktop.png'
                except Exception as error:result['screenshot_reason']=str(error)
            except Exception as error:result.update(status='failed',error=str(error))
            finally:
                (smoke_output/'ui-smoke.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
                window.close()
        root.after(1500,finish)
    root.mainloop();return result


def main(argv=None):
    multiprocessing.freeze_support()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--memory-budget-mb',type=int,default=DEFAULT_MEMORY_BUDGET_MB,help=f'Observed managed-process memory limit in MB ({MIN_MEMORY_BUDGET_MB}-{MAX_MEMORY_BUDGET_MB}; default: {DEFAULT_MEMORY_BUDGET_MB}).')
    parser.add_argument('--self-test',action='store_true',help='Exercise persistent memory, worker jobs and neural learning without opening a window.')
    parser.add_argument('--check-dependencies',action='store_true',help='Exercise bundled native dependencies without a window.')
    parser.add_argument('--require-ocr-tools',action='store_true',help='Require functional English OCR and PDF helper executables in the dependency check.')
    parser.add_argument('--ui-smoke-test',type=Path,metavar='OUTPUT',help='Construct the real desktop UI, capture it if supported, then close.')
    parser.add_argument('--review-smoke-test',type=Path,metavar='OUTPUT',help='Exercise the source drawing, geometry correction and draft-saving UI, then close.')
    parser.add_argument('--correction-smoke-test',type=Path,metavar='OUTPUT',help='Exercise actual desktop correction submission and regenerated native world readback.')
    parser.add_argument('--planning-pilot-smoke-test',type=Path,metavar='OUTPUT',help='Exercise planning discovery through a managed worker and verify retained evidence.')
    parser.add_argument('--web-smoke-test',type=Path,metavar='OUTPUT',help='Exercise offline web citations and persistent memory through a managed worker.')
    parser.add_argument('--web-planning-smoke-test',type=Path,metavar='OUTPUT',help='Exercise automatic application-to-original-PDF analysis through a managed worker.')
    parser.add_argument('--planning-collection-smoke-test',type=Path,metavar='OUTPUT',help='Exercise automatic follow-up batches and restart without reanalysis.')
    parser.add_argument('--runtime-worker',nargs=argparse.REMAINDER,help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if not 1<=args.workers<=4 or not MIN_MEMORY_BUDGET_MB<=args.memory_budget_mb<=MAX_MEMORY_BUDGET_MB:parser.error(f'Use 1-4 workers and {MIN_MEMORY_BUDGET_MB}-{MAX_MEMORY_BUDGET_MB} MB observed worker memory.')
    if args.runtime_worker is not None:
        from .desktop_runtime import worker_main
        return worker_main(args.runtime_worker)
    if args.check_dependencies:
        result=check_dependencies(require_ocr_tools=args.require_ocr_tools);print(json.dumps(result,sort_keys=True));return int(result['status']!='passed')
    if args.review_smoke_test is not None:
        from .desktop_review_ui import smoke_test
        result=smoke_test(args.review_smoke_test);print(json.dumps(result,sort_keys=True));return int(result.get('status')!='passed')
    if args.correction_smoke_test is not None:
        from .desktop_correction_smoke import run
        result=run(args.correction_smoke_test);print(json.dumps(result,sort_keys=True));return int(result.get('status')!='passed')
    if args.planning_pilot_smoke_test is not None:
        from .desktop_planning_smoke import run
        result=run(args.planning_pilot_smoke_test);print(json.dumps(result,sort_keys=True));return int(result.get('status')!='passed')
    if args.web_smoke_test is not None:
        from .desktop_web_smoke import run
        result=run(args.web_smoke_test);print(json.dumps(result,sort_keys=True));return int(result.get('status')!='passed')
    if args.web_planning_smoke_test is not None:
        from .desktop_web_planning_smoke import run
        result=run(args.web_planning_smoke_test);print(json.dumps(result,sort_keys=True));return int(result.get('status')!='passed')
    if args.planning_collection_smoke_test is not None:
        from .desktop_planning_collection_smoke import run
        result=run(args.planning_collection_smoke_test);print(json.dumps(result,sort_keys=True));return int(result.get('status')!='passed')
    if args.self_test:
        from .desktop_runtime import self_test
        if args.data_dir is None:
            with tempfile.TemporaryDirectory(prefix='voxel-desktop-self-test-') as directory:result=self_test(data_directory=Path(directory),workers=args.workers)
        else:result=self_test(data_directory=args.data_dir,workers=args.workers)
        print(json.dumps(result,sort_keys=True,default=str));return int(result.get('status')!='passed')
    directory=args.data_dir or default_data_directory()
    if args.ui_smoke_test is not None:
        result=launch(directory,args.workers,args.memory_budget_mb,args.ui_smoke_test);print(json.dumps(result,sort_keys=True));return int(result.get('status')!='passed')
    launch(directory,args.workers,args.memory_budget_mb);return 0


if __name__=='__main__':raise SystemExit(main())
