"""Bounded CPU desktop workers with durable memory and reviewed neural updates."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from .desktop_memory import MemoryStore, canonical, digest, source_separated_split

KINDS={'area_pilot','world_pilot','alton_world','building_batch','inspect_evidence','import_feedback','train_ranker','reason',
       'prepare_review','reconstruction_benchmark','regenerate_corrections','planning_source_pilot','web_research','web_planning_pilot','planning_collection','planning_world_preview','train_study_components'}
HEAVY={'area_pilot','world_pilot','alton_world','building_batch','reason','prepare_review','reconstruction_benchmark','regenerate_corrections','planning_source_pilot','web_research','web_planning_pilot','planning_collection','planning_world_preview','train_study_components'}
MAX_JSON_BYTES=16_000_000
MIN_MEMORY_BUDGET_MB=512
MAX_MEMORY_BUDGET_MB=16*1024
DEFAULT_MEMORY_BUDGET_MB=MAX_MEMORY_BUDGET_MB


def read_json(path,limit=MAX_JSON_BYTES):
    path=Path(path)
    if not path.is_file() or path.stat().st_size>limit:raise ValueError('A bounded existing JSON file is required: '+str(path))
    def invalid(value):raise ValueError('Nonfinite JSON constant: '+value)
    return json.loads(path.read_text(encoding='utf-8'),parse_constant=invalid)


def file_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+'.partial')
    with temp.open('w',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())
    for attempt in range(5):
        try:temp.replace(path);return
        except PermissionError:
            if attempt==4:raise
            time.sleep(.02*(attempt+1))


def resolve_path(config_path,value):
    if not isinstance(value,str) or not value:raise ValueError('A source path is required')
    return (Path(config_path).parent/Path(value)).resolve()


def _study_training_options(epochs,hidden_units):
    if type(epochs) is not int or not 1<=epochs<=300:
        raise ValueError('Study component training requires one to 300 epochs')
    if type(hidden_units) is not int or not 4<=hidden_units<=32:
        raise ValueError('Study component training requires four to 32 hidden units')


class DirectoryLock:
    def __init__(self,path):
        self.stream=None
        try:
            self.stream=Path(path).open('a+b');self.stream.seek(0)
            # Windows may reject reading a byte already locked by another
            # instance. Initialization and locking share the same error path.
            if self.stream.read(1)==b'':self.stream.write(b'0');self.stream.flush()
            self.stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except (OSError,IOError) as error:
            if self.stream is not None:self.stream.close()
            raise ValueError('This data directory is already open in another Voxel Mapper process') from error

    def close(self):
        if self.stream.closed:return
        self.stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.stream,fcntl.LOCK_UN)
        self.stream.close()


def _terminate(process):
    import psutil
    try:
        parent=psutil.Process(process.pid);children=parent.children(recursive=True)
        for child in children:
            try:child.terminate()
            except psutil.Error:pass
        try:parent.terminate()
        except psutil.Error:pass
        _,alive=psutil.wait_procs(children+[parent],timeout=2)
        for item in alive:
            try:item.kill()
            except psutil.Error:pass
    except psutil.Error:
        if process.poll() is None:process.kill()
    try:process.wait(timeout=3)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)


class DesktopRuntime:
    def __init__(self,data_directory,workers=2,memory_budget_mb=DEFAULT_MEMORY_BUDGET_MB):
        if type(workers) is not int or not 1<=workers<=4:raise ValueError('Choose one to four CPU workers')
        if type(memory_budget_mb) is not int or not MIN_MEMORY_BUDGET_MB<=memory_budget_mb<=MAX_MEMORY_BUDGET_MB:raise ValueError(f'Choose a {MIN_MEMORY_BUDGET_MB}–{MAX_MEMORY_BUDGET_MB} MB managed-process memory budget')
        self.directory=Path(data_directory).expanduser().resolve();self.directory.mkdir(parents=True,exist_ok=True)
        self._directory_lock=DirectoryLock(self.directory/'runtime.lock')
        try:self.store=MemoryStore(self.directory)
        except BaseException:self._directory_lock.close();raise
        self.workers=workers;self.memory_budget_mb=memory_budget_mb;self._closed=False;self._mutex=threading.RLock()
        self._training_mutex=threading.Lock();self._heavy=threading.Semaphore(1);self._events={};self._futures={};self._processes={}
        self._pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='voxel-worker')
        self._learning_lock=threading.RLock()
        self.store.set_setting('profile',{'minimum_system_ram_gb':6,'gpu_required':False,'workers':workers,'memory_budget_mb':memory_budget_mb,'heavy_jobs_at_once':1})
        if self.store.setting('continuous_learning') is None:self.store.set_setting('continuous_learning',True)
        self._validate_active()
        self._maybe_auto_train()

    def _validate_active(self):
        active=self.store.setting('active_model')
        if active:
            from .neural_learning import validate_model
            try:
                model=read_json(active['path'],1000000);validate_model(model)
                if model['artifact_sha256']!=active['sha256'] or not model['production_eligible']:raise ValueError('Active checkpoint integrity/eligibility failed')
            except (OSError,ValueError,KeyError) as error:
                self.store.set_setting('active_model',None);self.store.set_setting('learning_state',{'status':'active_checkpoint_withheld','reason':str(error)});self.store.event(None,'Active model withheld: '+str(error),'error')

    def submit(self,kind,config_path):
        if kind not in KINDS:raise ValueError('Unsupported desktop operation')
        config_path=Path(config_path).expanduser().resolve();config=read_json(config_path)
        if not isinstance(config,dict):raise ValueError('Desktop operation requires a JSON object')
        with self._mutex:
            if self._closed:raise RuntimeError('Desktop runtime is closed')
            active_count=sum(not f.done() for f in self._futures.values())
            if active_count>=64:raise ValueError('Desktop job queue is full')
            jid=uuid.uuid4().hex;directory=self.directory/'jobs'/jid;directory.mkdir(parents=True)
            write_json(directory/'submitted-config.json',config)
            self.store.add_job({'id':jid,'kind':kind,'config_path':str(config_path),'config_sha256':file_hash(config_path),'output_directory':str(directory/'output')})
            self._events[jid]=threading.Event();self.store.event(jid,'Queued '+kind)
            self._futures[jid]=self._pool.submit(self._execute,jid)
        return jid

    def submit_area(self,preset_id,*,evidence_directory=None,download_missing=False):
        from .desktop_area import PRESETS
        if preset_id not in {p['id'] for p in PRESETS}:raise ValueError('Choose a registered area preset')
        if type(download_missing) is not bool:raise ValueError('Download setting must be boolean')
        config={'preset':preset_id,'download_missing':download_missing}
        if evidence_directory:config['evidence_directory']=str(Path(evidence_directory).expanduser().resolve())
        path=self.directory/'area-requests'/(uuid.uuid4().hex+'.json');write_json(path,config)
        return self.submit('area_pilot',path)

    def submit_review(self,preset,*,evidence_directory=None):
        """Prepare a review queue; this never supplies reviewed outcomes."""
        if preset not in ('wicker','synthetic_demo','correction_demo'):raise ValueError('Choose a supported review preset')
        config={'preset':preset}
        if evidence_directory:config['evidence_directory']=str(Path(evidence_directory).expanduser().resolve())
        path=self.directory/'review-requests'/(uuid.uuid4().hex+'.json');write_json(path,config)
        return self.submit('prepare_review',path)

    def submit_web(self,query='',urls=None,*,allowed_hosts=None,model='',offline=False,refresh=True):
        from .web_research import VERSION,validate
        from .web_evidence import DEFAULT_HOSTS
        config={'version':VERSION,'query':query,'urls':urls or [],
            'allowed_hosts':list(DEFAULT_HOSTS) if allowed_hosts is None else allowed_hosts,
            'model':model,'offline':offline,'refresh':refresh}
        validate(config)
        path=self.directory/'web-requests'/(uuid.uuid4().hex+'.json');write_json(path,config)
        return self.submit('web_research',path)

    def submit_web_planning(self,application_reference,query='',urls=None,*,allowed_hosts=None,model='',offline=False,refresh=True,collect=False):
        if type(collect) is not bool:raise ValueError('Explicit follow-up collection setting required')
        from .web_planning_pilot import VERSION,validate
        from .web_research import VERSION as WEB_VERSION
        from .web_evidence import DEFAULT_HOSTS
        config={'version':VERSION,'area_id':application_reference,'application_reference':application_reference,
            'research':{'version':WEB_VERSION,'query':query,'urls':urls or [],
                'allowed_hosts':list(DEFAULT_HOSTS) if allowed_hosts is None else allowed_hosts,
                'model':model,'offline':offline,'refresh':refresh}}
        validate(config)
        if collect:
            from .planning_collection import VERSION as COLLECTION_VERSION,validate as validate_collection
            request={'version':COLLECTION_VERSION,'pilot':config};validate_collection(request)
            path=self.directory/'web-planning-requests'/(uuid.uuid4().hex+'.json');write_json(path,request)
            return self.submit('planning_collection',path)
        path=self.directory/'web-planning-requests'/(uuid.uuid4().hex+'.json');write_json(path,config)
        return self.submit('web_planning_pilot',path)

    def submit_reviewed_feedback(self,feedback_path):
        """Explicit UI import uses the same durable reviewed-feedback operation."""
        path=Path(feedback_path).expanduser().resolve()
        if not path.is_file():raise ValueError('Choose an existing reviewed feedback file')
        config=self.directory/'review-requests'/(uuid.uuid4().hex+'.json')
        write_json(config,{'feedback_path':str(path)})
        return self.submit('import_feedback',config)

    def submit_planning_world_preview(self,completed_job_id,*,alternative_ids=None):
        """Export pinned design alternatives to separate flat hypothesis worlds."""
        from .planning_world_preview import VERSION,validate
        try:job=self.store.job(completed_job_id)
        except KeyError as error:raise ValueError('Select a completed planning job first') from error
        if (job['status']!='completed' or job['kind'] not in
                ('planning_source_pilot','web_planning_pilot','planning_collection')):
            raise ValueError('Select a completed planning source, web planning or collection job first')
        name='analysis/design-massing.json' if job['kind']=='web_planning_pilot' else 'design-massing.json'
        root=Path(job['output_directory']).resolve();path=(root/name).resolve()
        pin=(job.get('result') or {}).get('output_sha256',{}).get(name)
        if (not path.is_relative_to(root) or not isinstance(pin,str) or len(pin)!=64
                or not path.is_file() or path.stat().st_size>8_000_000 or file_hash(path)!=pin):
            raise ValueError('Saved design massing review is missing or changed; run the planning analysis again')
        config={'version':VERSION,'review_path':str(path),'review_sha256':pin}
        if alternative_ids is not None:config['alternative_ids']=alternative_ids
        validate(config)
        request=self.directory/'planning-world-requests'/(uuid.uuid4().hex+'.json')
        write_json(request,config)
        return self.submit('planning_world_preview',request)

    def submit_regeneration(self,saved_review,*,world=True,benchmark_path=None):
        if type(world) is not bool:raise ValueError('World preview setting must be boolean')
        directory=Path(saved_review).expanduser().resolve()
        config={'review_directory':str(directory),'review_report_sha256':file_hash(directory/'report.json'),'world':world}
        if benchmark_path:
            path=Path(benchmark_path).expanduser().resolve()
            config.update(benchmark_path=str(path),benchmark_sha256=file_hash(path))
        request=self.directory/'correction-requests'/(uuid.uuid4().hex+'.json');write_json(request,config)
        return self.submit('regenerate_corrections',request)

    def submit_study_training(self,dataset_directory,*,epochs=150,hidden_units=16):
        """Fit an exploratory crop recognizer; never activate a building ranker."""
        _study_training_options(epochs,hidden_units)
        directory=Path(dataset_directory).expanduser().resolve();manifest=directory/'dataset.json'
        dataset=read_json(manifest)
        if not isinstance(dataset,dict) or dataset.get('version')!='retained-study-dataset-v1':
            raise ValueError('Choose a retained-study-dataset-v1 directory')
        config={'dataset_directory':str(directory),'dataset_sha256':file_hash(manifest),
                'epochs':epochs,'hidden_units':hidden_units}
        request=self.directory/'study-training-requests'/(uuid.uuid4().hex+'.json')
        write_json(request,config)
        return self.submit('train_study_components',request)

    def cancel(self,job_id):
        with self._mutex:
            event=self._events.get(job_id);future=self._futures.get(job_id)
            if event is None or future is None or future.done():return False
            job=self.store.job(job_id)
            if job['status'] in ('completed','failed','cancelled','interrupted'):return False
            event.set()
            if job['kind']=='train_ranker' and self.store.setting('last_auto_job')==job_id:self.store.set_setting('cancelled_auto_dataset',self.store.setting('last_auto_dataset_sha256'))
            Path(job['output_directory']).parent.joinpath('cancel').touch()
            if future.cancel():self.store.update_job(job_id,status='cancelled',message='Cancelled before execution')
            else:self.store.update_job(job_id,status='cancelling',message='Cancelling managed worker')
            self.store.event(job_id,'Cancellation requested');return True

    def _acquire(self,semaphore,cancelled):
        while not semaphore.acquire(timeout=.1):
            if cancelled.is_set():raise CancelledError()
        if cancelled.is_set():semaphore.release();raise CancelledError()

    def _execute(self,jid):
        job=self.store.job(jid);cancelled=self._events[jid];kind=job['kind'];heavy=False;training=False
        try:
            if kind in HEAVY:self._acquire(self._heavy,cancelled);heavy=True
            if kind=='train_ranker':self._acquire(self._training_mutex,cancelled);training=True
            if cancelled.is_set():raise CancelledError()
            if file_hash(job['config_path'])!=job['config_sha256']:raise ValueError('Queued input JSON changed; submit a new job')
            self.store.update_job(jid,status='running',progress=.02,message='Running '+kind)
            if kind=='import_feedback':result=self._import_feedback(job)
            else:result=self._subprocess_job(job,cancelled)
            with self._mutex:
                if cancelled.is_set():raise CancelledError()
                if kind=='train_ranker':self._store_checkpoint(job,result)
                if kind=='inspect_evidence':
                    for observation in result['observations']:self.store.remember('source_observation',observation['path'],observation)
                if kind in ('web_research','web_planning_pilot','planning_collection'):
                    for observation in result['sources']:
                        self.store.remember('web_source_observation',observation['url'],observation)
                if kind=='area_pilot':
                    self.store.remember('area_generation',jid,{'preset':result['desktop_area']['preset'],
                        'source_report':result['desktop_area']['source_report'],'readiness':result['readiness'],
                        'generated_voxel_records_by_kind':result['generated_voxel_records_by_kind'],
                        'physical_correctness_label_generated':False})
                self.store.remember('job_outcome',jid,{'kind':kind,'status':result.get('status','completed'),'artifact_directory':job['output_directory'],
                    'result_sha256':digest(result),'physical_correctness_label_generated':False})
                self.store.update_job(jid,status='completed',progress=1,message=result.get('status','Completed'),result=result)
                self.store.event(jid,'Completed '+kind+'; generated predictions and exports are not correctness labels')
        except CancelledError:
            self.store.update_job(jid,status='cancelled',message='Cancelled; partial output retained separately')
            self.store.event(jid,'Worker cancelled; checkpoint was not promoted','warning')
        except Exception as error:
            self.store.update_job(jid,status='failed',error=f'{type(error).__name__}: {error}',message=str(error)[:500])
            self.store.event(jid,f'{type(error).__name__}: {error}','error')
        finally:
            if heavy:self._heavy.release()
            if training:self._training_mutex.release()
            # A review import can arrive while a trainer is active. Recheck
            # after its terminal status is stored so the newest snapshot is
            # scheduled without requiring another import or application restart.
            if kind in ('import_feedback','train_ranker') and not self._closed:self._maybe_auto_train()

    def _import_feedback(self,job):
        config=read_json(job['config_path']);path=resolve_path(job['config_path'],config.get('feedback_path'));feedback_pin=file_hash(path);feedback=read_json(path)
        if file_hash(path)!=feedback_pin:raise ValueError('Feedback file changed during import')
        if feedback.get('version')!='building-feedback-v1':raise ValueError('A building-feedback-v1 reviewed dataset is required')
        if 'continuous' in config and type(config['continuous']) is not bool:raise ValueError('continuous must be boolean')
        split=None
        if 'split_path' in config:
            split_path=resolve_path(job['config_path'],config['split_path']);split=read_json(split_path)
            for key in ('training_buildings','evaluation_buildings'):
                values=split.get(key)
                if not isinstance(values,list) or any(not isinstance(v,str) or not v for v in values) or len(set(values))!=len(values):raise ValueError('Explicit unique building split required')
            if set(split['training_buildings'])&set(split['evaluation_buildings']):raise ValueError('Building split leakage')
        imported=self.store.import_feedback(feedback.get('records'))
        if split is not None:self.store.set_setting('explicit_split',split)
        if 'continuous' in config:
            self.store.set_setting('continuous_learning',config['continuous'])
            if config['continuous']:self.store.set_setting('cancelled_auto_dataset',None)
        result={'status':'reviewed_feedback_imported','imported':imported,'retained_records':len(self.store.feedback()),'source_feedback_sha256':feedback_pin,
            'review_provenance':'declared independent review/source verification; references are audit pointers, not authenticated signatures',
            'training_labels_generated':0}
        output=Path(job['output_directory']);output.mkdir();write_json(output/'report.json',result);return result

    def _training_dataset(self):
        records=self.store.feedback();split=self.store.setting('explicit_split')
        if split is None:
            split,assignments=source_separated_split(records,self.store.setting('split_assignments',{}));self.store.set_setting('split_assignments',assignments)
        return records,split

    def _maybe_auto_train(self):
        with self._learning_lock:
            if self._closed or not self.store.setting('continuous_learning',True):return
            if any(j['kind']=='train_ranker' and j['status'] in ('queued','running','cancelling') for j in self.store.jobs()):return
            try:
                records,split=self._training_dataset();train=set(split.get('training_buildings',[]));evaluation=set(split.get('evaluation_buildings',[]))
                a=[r for r in records if r['building_id'] in train];b=[r for r in records if r['building_id'] in evaluation]
                if len(train)<5 or len(evaluation)<5 or len(a)<100 or len(b)<20 or any({r['outcome'] for r in rows}!={'accepted','rejected'} for rows in (a,b)):
                    self.store.set_setting('learning_state',{'status':'awaiting_reviewed_dataset','training_records':len(a),'evaluation_records':len(b),
                        'training_buildings':len(train),'evaluation_buildings':len(evaluation),'required':'100 training records, 20 evaluation records, five independent buildings per split and both outcomes'});return
                fingerprint=digest({'records':records,'split':split})
                previous=self.store.setting('last_auto_dataset_sha256')
                attempts=self.store.setting('auto_training_attempts',{'dataset':fingerprint,'count':0})
                if attempts.get('dataset')!=fingerprint:attempts={'dataset':fingerprint,'count':0}
                if self.store.setting('cancelled_auto_dataset')==fingerprint:return
                if previous==fingerprint:
                    previous_job=self.store.setting('last_auto_job')
                    state=self.store.job(previous_job)['status'] if previous_job else 'interrupted'
                    if state=='completed':return
                    if attempts['count']>=3:
                        self.store.set_setting('learning_state',{'status':'retry_limit_reached','dataset_sha256':fingerprint,'reason':'Three interrupted/failed attempts retained; inspect logs or submit a manual training job'});return
                directory=self.directory/'datasets'/fingerprint;directory.mkdir(parents=True,exist_ok=True)
                write_json(directory/'feedback.json',{'version':'building-feedback-v1','records':records});write_json(directory/'split.json',split)
                write_json(directory/'training-job.json',{'feedback_path':'feedback.json','split_path':'split.json','epochs':300,'automatic':True})
                jid=self.submit('train_ranker',directory/'training-job.json');self.store.set_setting('last_auto_dataset_sha256',fingerprint)
                self.store.set_setting('last_auto_job',jid);self.store.set_setting('auto_training_attempts',{'dataset':fingerprint,'count':attempts['count']+1})
                self.store.set_setting('learning_state',{'status':'training_queued','job_id':jid,'dataset_sha256':fingerprint})
            except (ValueError,KeyError,RuntimeError) as error:
                self.store.set_setting('learning_state',{'status':'learning_held','reason':str(error)});self.store.event(None,'Continuous learning held: '+str(error),'warning')

    def _subprocess_job(self,job,cancelled):
        directory=Path(job['output_directory']).parent;request=directory/'request.json';active=self.store.setting('active_model')
        payload={'version':'desktop-worker-v1','kind':job['kind'],'config_path':job['config_path'],'config_sha256':job['config_sha256'],
            'output_directory':job['output_directory'],'result_path':str(directory/'worker-result.json'),'progress_path':str(directory/'progress.json'),
            'cancel_path':str(directory/'cancel'),'active_model':active,'memory_context':self.store.context(max_characters=max(0,min(2048,4096-len(str(read_json(job['config_path']).get('prompt','')))))) if job['kind'] in ('reason','web_research','web_planning_pilot','planning_collection') else ''}
        import psutil
        payload.update(parent_pid=os.getpid(),parent_created=psutil.Process(os.getpid()).create_time())
        write_json(request,payload)
        command=([sys.executable,'--runtime-worker','--request',str(request)] if getattr(sys,'frozen',False)
                 else [sys.executable,'-m','voxel_mapper.desktop_runtime','--worker','--request',str(request)])
        env=dict(os.environ)
        for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):env[key]='1'
        import psutil
        kwargs={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
        log_path=directory/'worker.log';peak=0.;result_path=Path(payload['result_path'])
        with log_path.open('wb') as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env,**kwargs)
            with self._mutex:self._processes[job['id']]=process
            try:
                while process.poll() is None:
                    if cancelled.wait(.1):_terminate(process);raise CancelledError()
                    # Poll the complete managed process tree. This is a measured
                    # cancellation budget, not an instantaneous OS memory limit.
                    try:
                        current=psutil.Process(os.getpid());tree=[current,*current.children(recursive=True)]
                        rss=sum(item.memory_info().rss for item in tree if item.is_running())/(1024**2)
                        peak=max(peak,rss)
                        if rss>self.memory_budget_mb:_terminate(process);raise MemoryError(f'Managed process memory {rss:.0f} MB exceeded {self.memory_budget_mb} MB budget')
                    except (psutil.NoSuchProcess,psutil.AccessDenied):pass
                    progress=Path(payload['progress_path'])
                    if progress.exists():
                        try:
                            value=read_json(progress,10000);fraction=float(value.get('progress',0))
                            if not 0<=fraction<=1:raise ValueError('Invalid worker progress')
                            self.store.update_job(job['id'],progress=fraction,message=str(value.get('message',''))[:500],peak_memory_mb=peak)
                        except (OSError,ValueError):pass
                if cancelled.is_set():raise CancelledError()
                self.store.update_job(job['id'],peak_memory_mb=peak)
                if process.returncode!=0:
                    detail=read_json(result_path,100000).get('error','') if result_path.exists() else log_path.read_bytes()[-4000:].decode('utf-8',errors='replace')
                    raise RuntimeError('Managed worker failed: '+str(detail))
                return read_json(result_path)
            finally:
                if process.poll() is None:_terminate(process)
                with self._mutex:self._processes.pop(job['id'],None)

    def _store_checkpoint(self,job,result):
        from .neural_learning import validate_model
        candidate_path=Path(job['output_directory'])/'candidate-model.json';model=read_json(candidate_path,1000000);validate_model(model)
        promoted=bool(model['production_eligible'])
        if result['candidate_sha256']!=model['artifact_sha256']:raise ValueError('Worker checkpoint/report mismatch')
        self.store.add_model(model,candidate_path,promoted)
        self.store.set_setting('learning_state',{'status':'checkpoint_promoted' if promoted else 'checkpoint_withheld',
            'candidate_sha256':model['artifact_sha256'],'evaluation':model['evaluation'],'previous_active_retained':not promoted})

    def set_continuous_learning(self,enabled):
        if type(enabled) is not bool:raise ValueError('Continuous learning setting must be boolean')
        self.store.set_setting('continuous_learning',enabled)
        if enabled:
            self.store.set_setting('cancelled_auto_dataset',None);self._maybe_auto_train()
        else:
            jid=self.store.setting('last_auto_job')
            if jid:self.cancel(jid)
        return enabled

    def snapshot(self):
        summary=self.store.summary();jobs=self.store.jobs()
        with self.store.connect() as db:events=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 40')]
        return {'jobs':jobs,'events':events,'memory':summary,'training':{'enabled':self.store.setting('continuous_learning',True),
            'active_model_sha256':summary['active_model']['sha256'] if summary['active_model'] else None,'feedback_records':summary['feedback_records'],
            'last_result':self.store.setting('learning_state',{'status':'awaiting_reviewed_dataset'})},
            'config':{'workers':self.workers,'memory_budget_mb':self.memory_budget_mb,'heavy_jobs_at_once':1},
            'data_directory':str(self.directory),'closed':self._closed}

    def close(self,wait=False):
        with self._mutex:
            if self._closed:return
            self._closed=True
            for jid,future in list(self._futures.items()):
                if not future.done():self.cancel(jid)
        self._pool.shutdown(wait=wait,cancel_futures=True)
        if wait:self._directory_lock.close()
        else:
            def release():
                for future in list(self._futures.values()):
                    try:future.result()
                    except BaseException:pass
                self._directory_lock.close()
            threading.Thread(target=release,name='voxel-runtime-close',daemon=True).start()


def _worker(request):
    kind=request['kind'];config_path=Path(request['config_path']);output=Path(request['output_directory'])
    if kind not in KINDS-{'import_feedback'} or request.get('version')!='desktop-worker-v1':raise ValueError('Registered desktop worker operation required')
    if file_hash(config_path)!=request['config_sha256']:raise ValueError('Worker configuration changed')
    config=read_json(config_path)
    def cancelled():return Path(request['cancel_path']).exists()
    def progress(value):write_json(request['progress_path'],value)
    if request.get('parent_pid'):
        def watch_parent():
            import psutil
            while True:
                try:alive=abs(psutil.Process(request['parent_pid']).create_time()-request['parent_created'])<.01
                except psutil.Error:alive=False
                if not alive:
                    for child in psutil.Process(os.getpid()).children(recursive=True):
                        try:child.kill()
                        except psutil.Error:pass
                    os._exit(3)
                time.sleep(.5)
        threading.Thread(target=watch_parent,name='voxel-parent-watch',daemon=True).start()
    if cancelled():raise CancelledError()
    progress({'progress':.03,'message':'Preparing '+kind})
    if kind=='train_study_components':
        if set(config)-{'dataset_directory','dataset_sha256','epochs','hidden_units'}:
            raise ValueError('Unsupported study component training settings')
        directory=resolve_path(config_path,config.get('dataset_directory'));manifest=directory/'dataset.json'
        pin=config.get('dataset_sha256')
        if (not isinstance(pin,str) or len(pin)!=64 or any(c not in '0123456789abcdef' for c in pin)
                or not manifest.is_file() or manifest.stat().st_size>MAX_JSON_BYTES or file_hash(manifest)!=pin):
            raise ValueError('Queued study dataset manifest is missing or changed')
        epochs=config.get('epochs',150);hidden_units=config.get('hidden_units',16)
        _study_training_options(epochs,hidden_units)
        from .study_component_learning import train
        result=train(directory,output,epochs=epochs,hidden_units=hidden_units,
                     cancelled=cancelled,progress=progress)
        if file_hash(manifest)!=pin:raise ValueError('Study dataset changed during training')
    elif kind=='planning_world_preview':
        from .planning_world_preview import run
        config={**config,'review_path':str(resolve_path(config_path,config.get('review_path')))}
        result=run(config,output,cancelled=cancelled,progress=progress)
    elif kind=='planning_collection':
        from .planning_collection import run,collection_key
        memory_root=output.parents[2]
        result=run(config,output,memory_root/'web-cache',memory_root/'planning-collections'/collection_key(config),
            memory=request.get('memory_context',''),cancelled=cancelled,progress=progress)
    elif kind=='web_planning_pilot':
        from .web_planning_pilot import run
        result=run(config,output,output.parents[2]/'web-cache',memory=request.get('memory_context',''),
            cancelled=cancelled,progress=progress)
    elif kind=='web_research':
        from .web_research import run
        result=run(config,output,output.parents[2]/'web-cache',memory=request.get('memory_context',''),
            cancelled=cancelled,progress=progress)
    elif kind=='area_pilot':
        from .desktop_area import run
        if set(config)-{'preset','evidence_directory','download_missing'}:raise ValueError('Unsupported area generation settings')
        result=run(config.get('preset'),output,evidence_directory=config.get('evidence_directory'),
            download_missing=config.get('download_missing',False),cache_directory=output.parents[2]/'source-cache',
            cancelled=cancelled,progress=progress)
    elif kind=='planning_source_pilot':
        from .planning_area_pilot import run
        base=resolve_path(config_path,config.get('source_directory','.'))
        result=run(config,lambda name:base/name,output,cancelled=cancelled,
            progress=lambda message:progress({'progress':.1,'message':message}))
    elif kind=='prepare_review':
        from .desktop_review_presets import prepare_demo,prepare_wicker
        if set(config)-{'preset','evidence_directory'}:raise ValueError('Unsupported review preparation settings')
        if config.get('preset') in ('synthetic_demo','correction_demo'):
            if config.get('evidence_directory'):raise ValueError('The synthetic example does not use real source inputs')
            result=prepare_demo(output,incorrect_geometry=config['preset']=='correction_demo')
        elif config.get('preset')=='wicker':
            result=prepare_wicker(output,evidence_directory=config.get('evidence_directory'),
                cache_directory=output.parents[2]/'source-cache',cancelled=cancelled,progress=progress)
        else:raise ValueError('Choose a supported review preset')
    elif kind=='regenerate_corrections':
        from .building_corrections import run
        if set(config)-{'review_directory','review_report_sha256','world','benchmark_path','benchmark_sha256'}:
            raise ValueError('Unsupported correction regeneration settings')
        directory=resolve_path(config_path,config.get('review_directory'))
        if file_hash(directory/'report.json')!=config.get('review_report_sha256'):raise ValueError('Queued saved review changed')
        benchmark_path=resolve_path(config_path,config['benchmark_path']) if config.get('benchmark_path') else None
        if benchmark_path and file_hash(benchmark_path)!=config.get('benchmark_sha256'):raise ValueError('Queued benchmark references changed')
        active=request.get('active_model');model=read_json(active['path'],1000000) if active and benchmark_path else None
        if model and model.get('artifact_sha256')!=active['sha256']:raise ValueError('Active comparison model changed')
        result=run(directory,output,world=config.get('world',True),benchmark_path=benchmark_path,model=model,cancelled=cancelled,progress=progress)
        if file_hash(directory/'report.json')!=config['review_report_sha256']:raise ValueError('Saved review changed during regeneration')
    elif kind=='reconstruction_benchmark':
        from .reconstruction_benchmark import run
        model=None;active=request.get('active_model');model_path=config.get('model_path')
        if model_path:
            path=resolve_path(config_path,model_path);pin=file_hash(path);model=read_json(path,1000000)
            if file_hash(path)!=pin:raise ValueError('Benchmark model changed during loading')
        elif active:
            model=read_json(active['path'],1000000)
            if model.get('artifact_sha256')!=active['sha256']:raise ValueError('Active benchmark model changed')
        result=run({k:v for k,v in config.items() if k!='model_path'},output,model=model)
    elif kind=='world_pilot':
        from .world_pilot import run
        result=run(config_path,output)
    elif kind=='alton_world':
        from .alton_world import generate_park
        source=resolve_path(config_path,config.get('source_output'));wicker=resolve_path(config_path,config.get('wicker_output'))
        budget=config.get('max_blocks',80000000)
        if type(budget) is not int or not 1<=budget<=80000000:raise ValueError('Full-park draft budget must be one to 80000000 blocks')
        if not source.is_dir() or not wicker.is_dir():raise ValueError('Both retained full-park and Wicker input directories are required')
        result=generate_park(source,wicker,output,max_blocks=budget)
    elif kind=='building_batch':
        from .building_pipeline import run
        from .neural_learning import baseline
        model=baseline();active=request.get('active_model')
        if active:
            from .neural_learning import validate_model
            model=read_json(active['path'],1000000);validate_model(model)
            if model['artifact_sha256']!=active['sha256'] or not model['production_eligible']:raise ValueError('Active neural model changed or is not eligible')
        result=run(config,output,model=model)
    elif kind=='inspect_evidence':
        paths=config.get('paths',[config.get('path')] if config.get('path') else [])
        if not isinstance(paths,list) or not 1<=len(paths)<=32:raise ValueError('Inspect one to 32 explicit evidence JSON paths')
        observations=[]
        for i,value in enumerate(paths):
            if cancelled():raise CancelledError()
            path=resolve_path(config_path,value);source_pin=file_hash(path);raw=read_json(path,32000000)
            if file_hash(path)!=source_pin:raise ValueError('Evidence changed during inspection')
            if not isinstance(raw,dict):raise ValueError('Evidence object required')
            observations.append({'path':str(path),'sha256':source_pin,'status':str(raw.get('status','unclassified'))[:200],
                'counts':{k:v for k,v in raw.get('counts',{}).items() if isinstance(k,str) and type(v) in (int,float) and len(k)<100},
                'limitations':['Stored source observation; no physical identity or correctness label is inferred']})
            progress({'progress':(i+1)/len(paths)*.9,'message':'Inspected '+path.name})
        output.mkdir();result={'status':'evidence_inspected','observations':observations,'training_labels_generated':0};write_json(output/'report.json',result)
    elif kind=='train_ranker':
        from .neural_learning import train,validate_model
        from .building_learning import _records
        path=resolve_path(config_path,config.get('feedback_path'));feedback_pin=file_hash(path);feedback=read_json(path)
        if feedback.get('version')!='building-feedback-v1':raise ValueError('Reviewed building feedback required')
        records=feedback.get('records');_records(records)
        if any(not isinstance(r.get('review_reference'),str) or not r['review_reference'].strip() for r in records):raise ValueError('Every training outcome needs an independent review reference')
        split_path=resolve_path(config_path,config['split_path']) if config.get('split_path') else None
        split_pin=file_hash(split_path) if split_path else None
        split=read_json(split_path) if split_path else source_separated_split(records)[0]
        active=request.get('active_model');parent_model=None
        if active:
            parent_model=read_json(active['path'],1000000);validate_model(parent_model)
            if parent_model['artifact_sha256']!=active['sha256'] or not parent_model['production_eligible']:raise ValueError('Active checkpoint changed or is not eligible')
        epochs=config.get('epochs',300)
        def training_progress(value):progress({'progress':min(.95,.05+.9*value.get('epoch',0)/max(1,epochs)),'message':'CPU neural training epoch '+str(value.get('epoch',0))})
        candidate=train(records,split['training_buildings'],split['evaluation_buildings'],parent_model,
            epochs=epochs,cancelled=cancelled,progress=training_progress)
        if cancelled():raise CancelledError()
        if file_hash(config_path)!=request['config_sha256'] or file_hash(path)!=feedback_pin or (split_path and file_hash(split_path)!=split_pin):raise ValueError('Training source/configuration changed')
        output.mkdir();write_json(output/'candidate-model.json',candidate)
        result={'status':'neural_checkpoint_evaluated','candidate_sha256':candidate['artifact_sha256'],'promotion_eligible':candidate['production_eligible'],
            'evaluation':candidate['evaluation'],'feedback_sha256':feedback_pin,'split':split,'training_labels_generated':0,
            'learning_scope':'six diagnostic feature candidate ranking; not a trained vision/language/world model'}
        write_json(output/'training-report.json',result)
    else:
        from .local_reasoning import reason
        result=reason(config.get('prompt',''),model=config.get('model',''),memory=request.get('memory_context',''),endpoint=config.get('endpoint','http://127.0.0.1:11434'),
            options=config.get('options'),cancelled=cancelled,progress=lambda value:progress({'progress':.5,'message':'Receiving optional local model response'}))
        output.mkdir();write_json(output/'reasoning.json',result)
    if cancelled():raise CancelledError()
    if file_hash(config_path)!=request['config_sha256']:raise ValueError('Worker configuration changed during execution')
    progress({'progress':1,'message':'Complete'});return result


def worker_main(argv=None):
    parser=argparse.ArgumentParser(description='Isolated Voxel Mapper desktop worker');parser.add_argument('--request',type=Path,required=True)
    args=parser.parse_args(argv);request=read_json(args.request,100000)
    try:
        result=_worker(request);write_json(request['result_path'],result);return 0
    except BaseException as error:
        write_json(request['result_path'],{'status':'cancelled' if isinstance(error,CancelledError) else 'failed','error':f'{type(error).__name__}: {error}'})
        import traceback
        traceback.print_exc();return 2 if isinstance(error,CancelledError) else 1


def _wait(runtime,jid,timeout=90):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        job=runtime.store.job(jid)
        if job['status'] in ('completed','failed','cancelled','interrupted'):return job
        time.sleep(.05)
    runtime.cancel(jid);raise TimeoutError('Desktop self-test job exceeded its time budget')


def create_smoke_world_job(directory):
    # A tiny explicitly synthetic terrain world exercises the actual frozen
    # GDAL/PROJ/native Bedrock writer and readback without network or real labels.
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    terrain=directory/'terrain.tif'
    with rasterio.open(terrain,'w',driver='GTiff',width=12,height=12,count=1,dtype='float32',crs='EPSG:4326',
                       transform=from_origin(0,.00012,.00001,.00001),nodata=-9999) as raster:
        raster.write(np.full((12,12),25,dtype='float32'),1)
    config={'bbox':[.00002,.00002,.00010,.00010],'voxel_size_m':1,
        'sources':[{'id':'synthetic-dem','url':'https://example.test/synthetic-dem','license':'CC0'}],
        'terrain':{'path':'terrain.tif','sha256':file_hash(terrain),'source_id':'synthetic-dem','units':'m','vertical_datum':'SYNTHETIC_TEST'}}
    write_json(directory/'config.json',config);write_json(directory/'features.geojson',{'type':'FeatureCollection','features':[]});write_json(directory/'reviews.json',[])
    def pin(name):return {'file':name,'sha256':file_hash(directory/name)}
    write_json(directory/'world-job.json',{'version':'world-pilot-v1','name':'Synthetic desktop CPU smoke world',
        'config':pin('config.json'),'features':pin('features.geojson'),'planning_review':pin('reviews.json')})
    return directory/'world-job.json'


def self_test(data_directory=None,workers=2):
    """Synthetic executable smoke: isolated worker, durable restart and CPU NN."""
    from .building_learning import FEATURES
    base=Path(data_directory) if data_directory else None
    if base:base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='voxel-desktop-self-test-',dir=base) as temp:
        root=Path(temp);write_json(root/'evidence.json',{'status':'synthetic_test_only','counts':{'known_points':4}})
        write_json(root/'inspect.json',{'paths':['evidence.json']})
        runtime=DesktopRuntime(root/'memory',workers=workers)
        try:
            jid=runtime.submit('inspect_evidence',root/'inspect.json');job=_wait(runtime,jid)
            if job['status']!='completed':raise RuntimeError(job.get('error') or job['status'])
            if runtime.snapshot()['memory']['knowledge_items']<1:raise AssertionError('Persistent observation missing')
        finally:runtime.close(wait=True)
        reopened=DesktopRuntime(root/'memory',workers=workers)
        try:
            if reopened.store.job(jid)['status']!='completed':raise AssertionError('Completed job did not survive restart')
            if reopened.snapshot()['memory']['knowledge_items']<1:raise AssertionError('Knowledge did not survive restart')
        finally:reopened.close(wait=True)
        world_job=create_smoke_world_job(root/'synthetic-world-input')
        native_runtime=DesktopRuntime(root/'native-memory',workers=workers)
        try:
            native_id=native_runtime.submit('world_pilot',world_job);native_result=_wait(native_runtime,native_id,timeout=120)
            if native_result['status']!='completed':raise RuntimeError(native_result.get('error') or native_result['status'])
            native_output=Path(native_result['output_directory'])
            if not (native_output/'park.mcworld').is_file():raise AssertionError('Frozen native world package missing')
            native_peak=native_result['peak_memory_mb']
        finally:native_runtime.close(wait=True)
        area_runtime=DesktopRuntime(root/'area-memory',workers=workers)
        try:
            area_id=area_runtime.submit_area('alton-terrain-paths');area_result=_wait(area_runtime,area_id,timeout=120)
            if area_result['status']!='completed':raise RuntimeError(area_result.get('error') or area_result['status'])
            area_report=area_result['result']
            if area_report['generated_voxel_records_by_kind']!={'terrain':7936,'road':178,'path':90}:raise AssertionError('Retained Alton area counts changed')
            if area_report['readiness']['planning_components_voxelized']!=0:raise AssertionError('Area preset invented accepted planning geometry')
            if not (Path(area_result['output_directory'])/'park.mcworld').is_file():raise AssertionError('Retained Alton world missing')
            area_peak=area_result['peak_memory_mb']
        finally:area_runtime.close(wait=True)
        # Exercise the same new entry points inside a frozen worker. The source
        # and decisions here are explicitly synthetic, and stay outside user data.
        from .desktop_review import load_session,bind_source,save_review
        from .reconstruction_benchmark import reference_digest
        review_runtime=DesktopRuntime(root/'review-memory',workers=workers)
        try:
            review_id=review_runtime.submit_review('synthetic_demo')
            review_job=_wait(review_runtime,review_id,timeout=90)
            if review_job['status']!='completed':raise RuntimeError(review_job.get('error') or review_job['status'])
            prepared=review_job['result'];session=load_session(prepared['queue_path'],prepared['batch_path'])
            for path in prepared['source_paths']:session=bind_source(session,path)
            row=session['records'][0]
            correction={'type':'dimension','component_id':row['candidate']['spec']['components'][0]['id'],
                'axis':'x','value_m':8.5,'source_sha256':row['source_sha256'][0],'source_page':1}
            draft=save_review(session,building_id=row['building_id'],candidate_sha256=row['candidate_sha256'],
                outcome=None,review_basis=None,review_reference='',corrections=[correction],output_directory=root/'correction-draft')
            if draft['feedback_path'] is not None:raise AssertionError('A correction draft created training feedback')
            regeneration_id=review_runtime.submit_regeneration(draft['output_directory'])
            regeneration_job=_wait(review_runtime,regeneration_id,timeout=120)
            if regeneration_job['status']!='completed':raise RuntimeError(regeneration_job.get('error') or regeneration_job['status'])
            regeneration_result=regeneration_job['result']
            if not Path(regeneration_result['corrected_world_path']).is_file():raise AssertionError('Regenerated native world missing')
            if 'all written blocks' not in regeneration_result['corrected_native']['world']['round_trip_validation']:
                raise AssertionError('Regenerated native world did not pass saved readback')
            regenerated=load_session(regeneration_result['queue_path'],regeneration_result['batch_path'])
            if any(regenerated['records'][0]['candidate']['gates'].values()):raise AssertionError('Regeneration bypassed independent review')
            geometry={'footprint_m':[[0,0],[8,0],[8,5],[0,5]],'height_m':4,'position_m':[0,0,0]}
            case={'id':'synthetic-exact','building_id':row['building_id'],'source_sha256':row['source_sha256'],
                'reference':{'geometry':geometry,'review_basis':'independent_review',
                    'review_reference':'Synthetic executable check; no real review claim'},'prediction':geometry}
            missing={**case,'id':'synthetic-missing','prediction':None}
            benchmark={'version':'reconstruction-benchmark-v1','dataset_kind':'synthetic','units':'metres',
                'coordinate_frame':'synthetic_local_xyz_metres','cases':[case,missing]}
            benchmark['reference_sha256']=reference_digest(benchmark)
            benchmark_path=root/'synthetic-benchmark.json';write_json(benchmark_path,benchmark)
            benchmark_id=review_runtime.submit('reconstruction_benchmark',benchmark_path)
            benchmark_job=_wait(review_runtime,benchmark_id,timeout=90)
            if benchmark_job['status']!='completed':raise RuntimeError(benchmark_job.get('error') or benchmark_job['status'])
            summary=benchmark_job['result']['summary']
            if summary['cases_within_thresholds']!=1 or summary['missing_predictions']!=1 or summary['all_cases_within_thresholds']:
                raise AssertionError('Benchmark did not preserve missing geometry as a failed/unassessed case')
            if review_runtime.store.summary()['feedback_records'] or review_runtime.store.summary()['checkpoints']:
                raise AssertionError('Review preparation/draft or benchmark created learning labels/checkpoints')
            review_peak=max(review_job['peak_memory_mb'],benchmark_job['peak_memory_mb'],regeneration_job['peak_memory_mb'])
        finally:review_runtime.close(wait=True)
        from .neural_learning import baseline,train,validate_model
        records=[]
        for phase in ('training','evaluation'):
            for i in range(5):
                building=f'synthetic-{phase}-{i}'
                for j in range(4):
                    value=float(j%2);identity=hashlib.sha256(f'{building}:{j}'.encode()).hexdigest()
                    records.append({'id':identity,'building_id':building,'candidate_sha256':identity,
                        'source_sha256':[hashlib.sha256(building.encode()).hexdigest()],
                        'features':{k:value for k in FEATURES},'outcome':'accepted' if value else 'rejected',
                        'review_basis':'independent_review','review_reference':'synthetic self-test only; not real evidence'})
        model=train(records,[f'synthetic-training-{i}' for i in range(5)],[f'synthetic-evaluation-{i}' for i in range(5)],epochs=20)
        validate_model(model)
        if model['parameters']==baseline()['parameters']:raise AssertionError('Neural weights did not learn')
        if model['production_eligible']:raise AssertionError('Undersized synthetic dataset should not qualify')
        return {'status':'passed','isolated_worker':'passed','persistent_job_and_observation_restart':'passed','cpu_neural_training':'passed',
            'undersized_checkpoint_withheld':True,'native_terrain_world_and_saved_readback':'passed','observed_managed_peak_memory_mb':native_peak,
            'real_alton_area_preset_and_readback':'passed','real_alton_area_peak_managed_memory_mb':area_peak,
            'source_linked_correction_draft':'passed','correction_draft_has_no_feedback':True,
            'correction_regeneration_world_and_readback':'passed','corrected_candidate_requires_independent_review':True,
            'managed_reconstruction_benchmark':'passed','benchmark_missing_prediction_remains_unassessed':True,
            'review_and_benchmark_peak_managed_memory_mb':review_peak,
            'synthetic_training_only':True,'trained_real_park_model':False}


if __name__=='__main__':
    arguments=sys.argv[1:]
    if arguments and arguments[0]=='--worker':arguments=arguments[1:]
    raise SystemExit(worker_main(arguments))
