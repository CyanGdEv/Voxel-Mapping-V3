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

JOB_KINDS = (
    ('World pilot from retained inputs', 'world_pilot'),
    ('Full Alton draft from retained inputs', 'alton_world'),
    ('Building batch / local previews', 'building_batch'),
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
                  f"Observed process memory budget: {config.get('memory_budget_mb',2048)} MB",
                  'Memory and checkpoints remain available after the application closes.',
                  'The neural model ranks evidence candidates; it does not certify physical geometry.'])
    return '\n'.join(lines)


def check_dependencies():
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
    optional={name:{'available':bool(shutil.which(name))} for name in ('tesseract','pdftotext','pdftoppm')}
    return {'status':'passed' if all(c['status']=='passed' for c in checks.values()) else 'failed',
            'checks':checks,'optional_external_tools':optional,
            'reasoning_model_weights_bundled':False}


class DesktopWindow:
    """Only the Tk event thread touches widgets; runtime calls use a UI queue."""
    def __init__(self,root,data_directory,workers=2,memory_budget_mb=2048):
        import tkinter as tk
        from tkinter import ttk
        from .desktop_runtime import DesktopRuntime
        self.tk=tk;self.ttk=ttk;self.root=root;self.runtime_factory=DesktopRuntime
        self.runtime=None;self.messages=Queue();self.dispatch=ThreadPoolExecutor(max_workers=1,thread_name_prefix='voxel-ui-dispatch')
        self.closed=False;self.last_snapshot={};self.poll_token=None;self.snapshot_pending=False;self.learning_pending=False
        style=ttk.Style(root)
        if os.name=='nt' and 'vista' in style.theme_names():style.theme_use('vista')
        elif 'clam' in style.theme_names():style.theme_use('clam')
        font_family='Segoe UI' if os.name=='nt' else 'DejaVu Sans'
        style.configure('.',font=(font_family,10))
        root.title('Voxel Mapper V3 - CPU desktop')
        root.geometry('1120x820');root.minsize(900,650)
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
        ttk.Spinbox(settings,from_=512,to=3072,increment=256,textvariable=self.memory_budget,width=8).grid(row=1,column=3,sticky='w',padx=8)
        ttk.Button(settings,text='Apply',command=self._apply_settings).grid(row=1,column=4)
        ttk.Label(settings,text='6 GB RAM default: 2 CPU workers, one heavy generation job at a time. Memory polling cancels over-budget jobs; it is not an OS reservation.',wraplength=980).grid(row=2,column=0,columnspan=5,sticky='w')
        settings.columnconfigure(1,weight=1)
        controls=ttk.LabelFrame(outer,text='Run a job',padding=10);controls.pack(fill='x',pady=12)
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
        actions=ttk.Frame(outer);actions.pack(fill='x',pady=(8,0))
        ttk.Button(actions,text='Cancel selected job',command=self._cancel).pack(side='left')
        ttk.Button(actions,text='Open data folder',command=self._open_directory).pack(side='left',padx=8)
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
        if not 1<=workers<=4 or not 512<=budget<=3072:raise ValueError('Choose 1-4 CPU workers and 512-3072 MB of observed worker memory.')
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
        for identifier in present-wanted:self.jobs.delete(identifier)
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
            if self.runtime:self.runtime.close(wait=False)
        finally:
            self.dispatch.shutdown(wait=False,cancel_futures=True);self.root.destroy()


def launch(data_directory,workers=2,memory_budget_mb=2048,smoke_output=None):
    import tkinter as tk
    root=tk.Tk();window=DesktopWindow(root,data_directory,workers,memory_budget_mb)
    result=None
    if smoke_output is not None:
        smoke_output=Path(smoke_output);smoke_output.mkdir(parents=True,exist_ok=True)
        result={'status':'passed','widgets_constructed':True,'screenshot':'unavailable'}
        def finish():
            try:
                root.update_idletasks()
                from PIL import ImageGrab
                box=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())
                ImageGrab.grab(bbox=box).save(smoke_output/'desktop.png');result['screenshot']='desktop.png'
            except Exception as error:result['screenshot_reason']=str(error)
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
    parser.add_argument('--memory-budget-mb',type=int,default=2048)
    parser.add_argument('--self-test',action='store_true',help='Exercise persistent memory, worker jobs and neural learning without opening a window.')
    parser.add_argument('--check-dependencies',action='store_true',help='Exercise bundled native dependencies without a window.')
    parser.add_argument('--ui-smoke-test',type=Path,metavar='OUTPUT',help='Construct the real desktop UI, capture it if supported, then close.')
    parser.add_argument('--runtime-worker',nargs=argparse.REMAINDER,help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if not 1<=args.workers<=4 or not 512<=args.memory_budget_mb<=3072:parser.error('Use 1-4 workers and 512-3072 MB observed worker memory.')
    if args.runtime_worker is not None:
        from .desktop_runtime import worker_main
        return worker_main(args.runtime_worker)
    if args.check_dependencies:
        result=check_dependencies();print(json.dumps(result,sort_keys=True));return int(result['status']!='passed')
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
