"""Source-linked correction workbench for the CPU desktop application.

Drawing pixels and generated local metre geometry are deliberately shown in
separate frames. A click annotates a proposed replacement; it never edits the
original candidate or supplies an automatic correctness label.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Queue
import copy
import math
import uuid

MAX_PREVIEW_PIXELS = 2000000
MAX_PREVIEW_DIMENSION = 4096
MAX_DISPLAY_EDGES = 10000
PROJECTIONS = {'xy': (0, 1), 'xz': (0, 2), 'yz': (1, 2)}


def geometry_preview(spec):
    """Build off the Tk thread and return a bounded wireframe display."""
    from .building_spec import build
    model = build(spec)
    components = []
    count = 0
    simplified = False
    bounds = [[math.inf, -math.inf] for _ in range(3)]
    for component in model['components']:
        mesh = component['mesh']
        for vertex in mesh['vertices']:
            for axis, value in enumerate(vertex):
                bounds[axis][0] = min(bounds[axis][0], value)
                bounds[axis][1] = max(bounds[axis][1], value)
        edges = []
        seen = set()
        for triangle in mesh['triangles']:
            if count >= MAX_DISPLAY_EDGES:
                simplified = True
                break
            for index in range(3):
                edge = tuple(sorted((triangle[index], triangle[(index + 1) % 3])))
                if edge in seen:
                    continue
                seen.add(edge)
                if count >= MAX_DISPLAY_EDGES:
                    simplified = True
                    break
                edges.append([mesh['vertices'][edge[0]], mesh['vertices'][edge[1]]])
                count += 1
        components.append({'id': component['id'], 'role': component['role'], 'edges': edges})
    return {'components': components, 'bounds': bounds, 'simplified': simplified,
            'edge_count': count, 'coordinate_frame': model['coordinate_frame'] if 'coordinate_frame' in model else 'local_xyz_metres_z_up'}


def render_pdf_preview(source, page):
    """Render a verified local PDF with a fixed pixel budget, checking its pin."""
    import hashlib
    import pymupdf
    path = Path(source['path'])
    if path.stat().st_size > 32000000:
        raise ValueError('PDF preview byte budget exceeded')
    with path.open('rb') as stream:
        raw = stream.read(32000001)
    if len(raw) > 32000000:
        raise ValueError('PDF preview byte budget exceeded')
    if hashlib.sha256(raw).hexdigest() != source['sha256']:
        raise ValueError('Original PDF changed; bind the correct source again.')
    with pymupdf.open(stream=raw, filetype='pdf') as document:
        if document.needs_pass:
            raise ValueError('The original PDF requires a password.')
        if type(page) is not int or not 1 <= page <= document.page_count:
            raise ValueError('Choose an existing one-based PDF page.')
        sheet = document[page - 1]
        area = float(sheet.rect.width) * float(sheet.rect.height)
        if not math.isfinite(area) or area <= 0:
            raise ValueError('The PDF has no usable page bounds.')
        scale = min(2., math.sqrt(MAX_PREVIEW_PIXELS / area) * .99)
        bounds = (sheet.rect * pymupdf.Matrix(scale, scale)).irect
        if (bounds.width < 1 or bounds.height < 1
                or max(bounds.width, bounds.height) > MAX_PREVIEW_DIMENSION
                or bounds.width * bounds.height > MAX_PREVIEW_PIXELS):
            raise ValueError('PDF preview dimensions exceed the bounded rendering budget')
        pixmap = sheet.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        if pixmap.width * pixmap.height > MAX_PREVIEW_PIXELS:
            raise ValueError('PDF preview pixel budget exceeded')
        return pixmap.tobytes('png')


class ReviewWindow:
    """Scrollable source/candidate review window; all file work is asynchronous."""
    def __init__(self, parent, output_root, on_feedback=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.ttk = ttk
        self.window = tk.Toplevel(parent)
        self.window.title('Voxel Mapper V3 - Review and correct geometry')
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        self.window.geometry(f'{min(1180, screen_w - 50)}x{min(820, screen_h - 90)}+20+20')
        self.window.minsize(min(900, screen_w - 50), min(560, screen_h - 90))
        self.output_root = Path(output_root)
        self.on_feedback = on_feedback
        self.session = None
        self.preview = None
        self.corrections = []
        self.draft_points = []
        self.last_report = None
        self.last_saved_report = None
        self.last_error = None
        self.closed = False
        self.pending = 0
        self.messages = Queue()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='voxel-review')
        self._token = None
        self._render_generation = 0
        self._source_generation = 0
        self._state_revision = 0
        self._candidate_states = {}
        self._active_key = None
        self._transform = None
        self._source_pil = None
        self._source_image = None
        self._displayed_source = None
        self._source_zoom = 1.
        self.queue_path = tk.StringVar()
        self.candidate_choice = tk.StringVar()
        self.component = tk.StringVar()
        self.projection = tk.StringVar(value='xz')
        self.source_choice = tk.StringVar()
        self.source_page = tk.IntVar(value=1)
        self.correction_type = tk.StringVar(value='outline')
        self.dimension = tk.StringVar()
        self.dimension_axis = tk.StringVar(value='x')
        self.translation = tk.StringVar(value='0, 0, 0')
        self.rotation = tk.StringVar(value='0')
        self.point_entry = tk.StringVar()
        self.outcome = tk.StringVar(value='unreviewed')
        self.review_basis = tk.StringVar(value='independent_review')
        self.review_reference = tk.StringVar()
        self.status = tk.StringVar(value='Open a source review queue to begin.')
        self.point_status = tk.StringVar(value='Click the geometry preview to trace a replacement polygon in metres.')
        self.source_status = tk.StringVar(value='Choose an original PDF whose checksum belongs to the candidate.')
        shell = ttk.Frame(self.window, padding=10)
        shell.pack(fill='both', expand=True)
        toolbar = ttk.Frame(shell)
        toolbar.pack(fill='x')
        ttk.Button(toolbar, text='Open review queue...', command=self._choose_queue).pack(side='left')
        self.resume_button = ttk.Button(toolbar, text='Resume saved review...', command=self._choose_saved_review)
        self.resume_button.pack(side='left', padx=(6, 0))
        ttk.Label(toolbar, textvariable=self.queue_path).pack(side='left', padx=10)
        ttk.Label(shell, text='Compare original drawing evidence with generated local geometry. Corrections remain proposals until independently checked.', wraplength=1050).pack(anchor='w', pady=(6, 8))
        viewport = tk.Canvas(shell, highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient='vertical', command=viewport.yview)
        viewport.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        viewport.pack(side='left', fill='both', expand=True)
        content = ttk.Frame(viewport)
        self._content_id = viewport.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda event: viewport.configure(scrollregion=viewport.bbox('all')))
        viewport.bind('<Configure>', lambda event: viewport.itemconfigure(self._content_id, width=event.width))
        self.viewport = viewport
        pick = ttk.Frame(content)
        pick.pack(fill='x', pady=(0, 8))
        ttk.Label(pick, text='Original candidate').grid(row=0, column=0, sticky='w')
        self.candidate_picker = ttk.Combobox(pick, textvariable=self.candidate_choice, state='readonly')
        self.candidate_picker.grid(row=0, column=1, sticky='ew', padx=8)
        self.candidate_picker.bind('<<ComboboxSelected>>', self._candidate_changed)
        pick.columnconfigure(1, weight=1)
        source_tools = ttk.Frame(content)
        source_tools.pack(fill='x', pady=(0, 6))
        ttk.Button(source_tools, text='Bind original PDF...', command=self._choose_pdf).grid(row=0, column=0)
        self.source_picker = ttk.Combobox(source_tools, textvariable=self.source_choice, state='readonly', width=28)
        self.source_picker.grid(row=0, column=1, sticky='ew', padx=8)
        self.source_picker.bind('<<ComboboxSelected>>', lambda event: self.render_source())
        ttk.Label(source_tools, text='Page').grid(row=0, column=2)
        ttk.Spinbox(source_tools, from_=1, to=10000, textvariable=self.source_page, width=5).grid(row=0, column=3, padx=6)
        ttk.Button(source_tools, text='Show page', command=self.render_source).grid(row=0, column=4)
        ttk.Button(source_tools, text='Zoom +', command=lambda: self._zoom_source(1.5)).grid(row=0, column=5, padx=(6, 0))
        ttk.Button(source_tools, text='Zoom -', command=lambda: self._zoom_source(1 / 1.5)).grid(row=0, column=6)
        source_tools.columnconfigure(1, weight=1)
        ttk.Label(content, textvariable=self.source_status, wraplength=1050).pack(anchor='w', pady=(0, 6))
        panels = ttk.Frame(content)
        panels.pack(fill='x')
        panels.columnconfigure(0, weight=1, uniform='preview')
        panels.columnconfigure(1, weight=1, uniform='preview')
        left = ttk.LabelFrame(panels, text='Original PDF page - drawing coordinates', padding=4)
        right = ttk.LabelFrame(panels, text='Generated candidate - local metre coordinates', padding=4)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 4))
        right.grid(row=0, column=1, sticky='nsew', padx=(4, 0))
        self.source_canvas = tk.Canvas(left, background='#e7e9ed', height=280, width=420, highlightthickness=0)
        self.source_canvas.pack(fill='both', expand=True)
        self.geometry_canvas = tk.Canvas(right, background='#f7f8fa', height=280, width=420, highlightthickness=0)
        self.geometry_canvas.pack(fill='both', expand=True)
        self.geometry_canvas.bind('<Button-1>', self._geometry_click)
        self.geometry_canvas.bind('<Configure>', lambda event: self._draw_geometry())
        self.source_canvas.bind('<Configure>', lambda event: self._draw_source())
        self.source_canvas.bind('<ButtonPress-1>', lambda event: self.source_canvas.scan_mark(event.x, event.y))
        self.source_canvas.bind('<B1-Motion>', lambda event: self.source_canvas.scan_dragto(event.x, event.y, gain=1))
        tools = ttk.Frame(content)
        tools.pack(fill='x', pady=8)
        ttk.Label(tools, text='Component').grid(row=0, column=0)
        self.component_picker = ttk.Combobox(tools, textvariable=self.component, state='readonly', width=23)
        self.component_picker.grid(row=0, column=1, sticky='ew', padx=6)
        self.component_picker.bind('<<ComboboxSelected>>', lambda event: self._clear_trace())
        ttk.Label(tools, text='Projection').grid(row=0, column=2)
        projection = ttk.Combobox(tools, textvariable=self.projection, values=tuple(PROJECTIONS), state='readonly', width=5)
        projection.grid(row=0, column=3, padx=6)
        projection.bind('<<ComboboxSelected>>', lambda event: self._clear_trace())
        ttk.Label(tools, text='Correction').grid(row=0, column=4)
        kind = ttk.Combobox(tools, textvariable=self.correction_type, values=('outline', 'opening', 'dimension', 'placement'), state='readonly', width=12)
        kind.grid(row=0, column=5, padx=6)
        kind.bind('<<ComboboxSelected>>', lambda event: self._clear_trace())
        tools.columnconfigure(1, weight=1)
        ttk.Label(content, textvariable=self.point_status, wraplength=1050).pack(anchor='w')
        exact = ttk.Frame(content)
        exact.pack(fill='x', pady=5)
        ttk.Label(exact, text='Exact polygon point (two projected metre coordinates)').pack(side='left')
        ttk.Entry(exact, textvariable=self.point_entry, width=20).pack(side='left', padx=6)
        ttk.Button(exact, text='Add exact point', command=self._add_exact_point).pack(side='left')
        values = ttk.Frame(content)
        values.pack(fill='x', pady=6)
        ttk.Label(values, text='Dimension (m)').grid(row=0, column=0)
        ttk.Entry(values, textvariable=self.dimension, width=9).grid(row=0, column=1, padx=6)
        ttk.Label(values, text='Axis').grid(row=0, column=2)
        ttk.Combobox(values, textvariable=self.dimension_axis, values=('x', 'y', 'z'), state='readonly', width=3).grid(row=0, column=3)
        ttk.Label(values, text='XYZ offset (m)').grid(row=0, column=4, padx=(8, 0))
        ttk.Entry(values, textvariable=self.translation, width=17).grid(row=0, column=5, padx=6)
        ttk.Label(values, text='Rotation (degrees)').grid(row=0, column=6)
        ttk.Entry(values, textvariable=self.rotation, width=7).grid(row=0, column=7, padx=6)
        edits = ttk.Frame(content)
        edits.pack(fill='x', pady=(0, 6))
        ttk.Button(edits, text='Undo trace point', command=self._undo_point).pack(side='left')
        ttk.Button(edits, text='Clear trace', command=self._clear_trace).pack(side='left', padx=6)
        self.add_button = ttk.Button(edits, text='Add correction', command=self.add_correction)
        self.add_button.pack(side='left')
        ttk.Button(edits, text='Remove selected correction', command=self._remove_correction).pack(side='left', padx=6)
        self.correction_list = tk.Listbox(content, height=3, exportselection=False)
        self.correction_list.pack(fill='x')
        decision = ttk.LabelFrame(content, text='Review the original candidate', padding=8)
        decision.pack(fill='x', pady=8)
        ttk.Label(decision, text='Corrections describe a replacement. Reject the original candidate or save a draft; corrected geometry is not automatically accepted.', wraplength=1020).grid(row=0, column=0, columnspan=4, sticky='w')
        ttk.Label(decision, text='Original outcome').grid(row=1, column=0, sticky='w', pady=6)
        ttk.Combobox(decision, textvariable=self.outcome, values=('unreviewed', 'accepted', 'rejected'), state='readonly', width=13).grid(row=1, column=1, sticky='w', padx=6)
        ttk.Label(decision, text='Review basis').grid(row=1, column=2, sticky='w')
        ttk.Combobox(decision, textvariable=self.review_basis, values=('independent_review', 'source_verified'), state='readonly', width=22).grid(row=1, column=3, sticky='ew', padx=6)
        ttk.Label(decision, text='External review reference').grid(row=2, column=0, sticky='w')
        ttk.Entry(decision, textvariable=self.review_reference).grid(row=2, column=1, columnspan=3, sticky='ew', padx=6)
        decision.columnconfigure(3, weight=1)
        actions = ttk.Frame(content)
        actions.pack(fill='x', pady=(0, 8))
        self.draft_button = ttk.Button(actions, text='Save correction draft', command=self.save_draft)
        self.draft_button.pack(side='left')
        self.save_button = ttk.Button(actions, text='Save reviewed decision', command=self.save_decision)
        self.save_button.pack(side='left', padx=8)
        self.import_button = ttk.Button(actions, text='Import saved reviewed feedback', command=self.import_feedback, state='disabled')
        self.import_button.pack(side='left')
        ttk.Label(content, textvariable=self.status, wraplength=1050).pack(anchor='w', pady=(0, 8))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        for variable in (self.outcome, self.review_basis, self.review_reference,
                         self.source_choice, self.source_page, self.component,
                         self.projection, self.correction_type, self.dimension,
                         self.dimension_axis, self.translation, self.rotation, self.point_entry):
            variable.trace_add('write', self._review_changed)
        self._poll()

    def _review_changed(self, *unused):
        self._state_revision += 1
        self.last_report = None
        self.import_button.state(['disabled'])

    @property
    def current_record(self):
        if not self.session:
            return None
        return next((row for row in self.session['records'] if self._candidate_label(row) == self.candidate_choice.get()), None)

    @staticmethod
    def _candidate_label(row):
        return f"{row['building_id']} / {row.get('candidate_id', row['candidate_sha256'][:12])}"

    def _background(self, action, success, message):
        if self.closed:
            return
        self.last_error = None
        self.pending += 1
        self.status.set(message)
        def run():
            try:
                self.messages.put((success, action(), None))
            except Exception as error:
                self.messages.put((None, None, str(error)))
        self.executor.submit(run)

    def _poll(self):
        if self.closed:
            return
        while True:
            try:
                callback, result, error = self.messages.get_nowait()
            except Empty:
                break
            self.pending = max(0, self.pending - 1)
            if error:
                self._error(error)
            elif callback:
                try:
                    callback(result)
                except Exception as problem:
                    self._error(str(problem))
        self._token = self.window.after(50, self._poll)

    def _error(self, message):
        self.last_error = str(message)
        self.status.set('Review needs attention: ' + str(message))

    def _choose_queue(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.window, title='Open a generated building review queue', filetypes=[('Review queue', '*.json')])
        if path:
            self.load_queue(path)

    def _choose_saved_review(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(parent=self.window, title='Choose a saved review or correction draft folder', initialdir=str(self.output_root))
        if path:
            self.load_saved_review(path)

    def load_saved_review(self, directory):
        """Resume an immutable saved result without importing its feedback."""
        from .desktop_review import resume_review
        if self.pending:
            self._error('Wait for the current review operation before resuming a saved review.')
            return
        self._review_changed()
        self._stash_state()
        def resumed(value):
            self._stash_state()
            session = value['session']
            row = next(row for row in session['records'] if row['building_id'] == value['building_id'] and row['candidate_sha256'] == value['candidate_sha256'])
            corrections = copy.deepcopy(value['corrections'])
            decision = value['decision'] or {}
            first = corrections[0] if corrections else {}
            variables = {
                'outcome': decision.get('outcome', 'unreviewed'),
                'review_basis': decision.get('review_basis', 'independent_review'),
                'review_reference': decision.get('review_reference', ''),
                'component': first.get('component_id', row['candidate']['spec']['components'][0]['id']),
                'projection': first.get('projection', 'xz'),
                'source_page': first.get('source_page', 1),
                'correction_type': first.get('type', 'outline'),
                'dimension': str(first.get('value_m', '')),
                'dimension_axis': first.get('axis', 'x'),
                'translation': ', '.join(str(v) for v in first.get('translation_m', [0, 0, 0])),
                'rotation': str(first.get('rotation_degrees', 0)),
                'point_entry': '',
            }
            key = (session['queue_sha256'], value['building_id'], value['candidate_sha256'])
            self._candidate_states[key] = {
                'corrections': corrections, 'draft_points': [], 'variables': variables,
                'source_sha256': first.get('source_sha256', row['source_sha256'][0]),
            }
            self._active_key = None
            self.session = session
            self.queue_path.set(session['queue_path'])
            self.candidate_picker.configure(values=[self._candidate_label(record) for record in session['records']])
            self.candidate_choice.set(self._candidate_label(row))
            self._candidate_changed()
            self.last_saved_report = value['report']
            self.last_report = None
            self.import_button.state(['disabled'])
            self.status.set('Saved review reopened with original source pins checked. No feedback was imported.')
        self._background(lambda: resume_review(directory), resumed, 'Checking saved corrections and original source evidence...')

    def load_queue(self, path, batch_path=None, source_paths=None):
        from .desktop_review import load_session, bind_source
        if self.pending:
            self._error('Wait for the current review operation before opening another queue.')
            return
        self._review_changed()
        self._stash_state()
        path = str(Path(path).expanduser().resolve())
        source_paths = tuple(source_paths or ())
        def load():
            session = load_session(path, batch_path=batch_path)
            for source_path in source_paths:
                session = bind_source(session, source_path)
            return session
        def loaded(session):
            self.session = session
            self.queue_path.set(path)
            self.candidate_picker.configure(values=[self._candidate_label(row) for row in session['records']])
            self.candidate_choice.set(self._candidate_label(session['records'][0]))
            self._candidate_changed()
        self._background(load, loaded, 'Opening pinned source review queue...')

    def _candidate_changed(self, event=None):
        record = self.current_record
        if not record:
            return
        self._stash_state()
        self._review_changed()
        self._active_key = (self.session['queue_sha256'], record['building_id'], record['candidate_sha256'])
        state = self._candidate_states.get(self._active_key)
        self.corrections = []
        self.draft_points = []
        self.preview = None
        self.last_report = None
        self.import_button.state(['disabled'])
        self.correction_list.delete(0, 'end')
        self.outcome.set('unreviewed')
        self.review_reference.set('')
        components = record['candidate']['spec']['components']
        self.component_picker.configure(values=[row['id'] for row in components])
        self.component.set(components[0]['id'])
        self._update_source_choices()
        if state:
            self.corrections = copy.deepcopy(state['corrections'])
            self.draft_points = copy.deepcopy(state['draft_points'])
            for key, value in state['variables'].items():
                getattr(self, key).set(value)
            source = next((label for label, sha in self._source_labels.items() if sha == state['source_sha256']), None)
            if source:
                self.source_choice.set(source)
            for annotation in self.corrections:
                self.correction_list.insert('end', f"{annotation['type']}: {annotation.get('component_id', 'building')} | source page {annotation['source_page']} | {annotation['source_sha256'][:12]}")
        self._source_pil = None
        self._displayed_source = None
        self._source_generation += 1
        self._draw_source()
        self._render_generation += 1
        generation = self._render_generation
        spec = copy.deepcopy(record['candidate']['spec'])
        def ready(preview):
            if generation != self._render_generation:
                return
            self.preview = preview
            self._draw_geometry()
            self.status.set('Candidate annotations restored. Save a fresh result to retain further edits.' if state else 'Candidate loaded. Bind original drawing evidence before adding corrections.')
        self._background(lambda: geometry_preview(spec), ready, 'Preparing local geometry preview...')
        sha = self._source_labels.get(self.source_choice.get())
        if sha in self.session['resolved_sources']:
            self.render_source()

    def _stash_state(self):
        if not self._active_key:
            return
        names = ('outcome', 'review_basis', 'review_reference', 'component', 'projection',
                 'source_page', 'correction_type', 'dimension', 'dimension_axis',
                 'translation', 'rotation', 'point_entry')
        values = {}
        for name in names:
            variable = getattr(self, name)
            try:
                values[name] = variable.get()
            except self.tk.TclError:
                values[name] = self.window.tk.globalgetvar(variable._name)
        self._candidate_states[self._active_key] = {
            'corrections': copy.deepcopy(self.corrections),
            'draft_points': copy.deepcopy(self.draft_points),
            'variables': values,
            'source_sha256': getattr(self, '_source_labels', {}).get(self.source_choice.get()),
        }

    def _update_source_choices(self):
        record = self.current_record
        self._source_labels = {sha + (' - bound' if sha in self.session['resolved_sources'] else ' - unbound'): sha for sha in record['source_sha256']}
        self.source_picker.configure(values=list(self._source_labels))
        self.source_choice.set(next(iter(self._source_labels), ''))
        self.source_page.set(1)

    def _choose_pdf(self):
        from tkinter import filedialog
        if not self.session:
            self._error('Open a review queue first.')
            return
        path = filedialog.askopenfilename(parent=self.window, title='Choose the matching original drawing PDF', filetypes=[('Original PDF', '*.pdf')])
        if path:
            self.bind_pdf(path)

    def bind_pdf(self, path):
        from .desktop_review import bind_source
        if not self.session:
            self._error('Open a review queue first.')
            return
        if self.pending:
            self._error('Wait for the current preview or source operation before binding another PDF.')
            return
        session = copy.deepcopy(self.session)
        def bound(value):
            if self.session['queue_sha256'] != session['queue_sha256']:
                return
            before = set(self.session['resolved_sources'])
            self.session = value
            self._update_source_choices()
            added = set(value['resolved_sources']) - before
            selected = next(iter(added), None)
            if selected:
                self.source_choice.set(next((label for label, sha in self._source_labels.items() if sha == selected), self.source_choice.get()))
            self.render_source()
        self._background(lambda: bind_source(session, path), bound, 'Verifying the original PDF checksum...')

    def render_source(self):
        try:
            sha = self._source_labels.get(self.source_choice.get())
            source = self.session['resolved_sources'].get(sha)
            if not source:
                raise ValueError('Bind this original PDF before previewing its pages.')
            page = self.source_page.get()
            self._source_generation += 1
            generation = self._source_generation
            self._displayed_source = None
            self._source_pil = None
            self._source_zoom = 1.
            self._draw_source()
            self.source_status.set(f'Original source {sha} | page {page} | source pixels and geometry use separate frames')
            def rendered(png):
                if (generation != self._source_generation
                        or self._source_labels.get(self.source_choice.get()) != sha
                        or self.source_page.get() != page):
                    return
                from PIL import Image
                from io import BytesIO
                self._source_pil = Image.open(BytesIO(png)).copy()
                self._displayed_source = (sha, page)
                self._draw_source()
                self.status.set('Original page verified and displayed. Corrections are recorded in local metres.')
            self._background(lambda: render_pdf_preview(source, page), rendered, 'Rendering the original drawing page...')
        except Exception as error:
            self._error(str(error))

    def _draw_source(self):
        self.source_canvas.delete('all')
        if self._source_pil is None:
            self.source_canvas.create_text(max(100, self.source_canvas.winfo_width() / 2), 120, text='Bind an original PDF\nto view its evidence here.', justify='center', fill='#475569')
            return
        from PIL import ImageTk
        image = self._source_pil.copy()
        width = max(50, self.source_canvas.winfo_width() - 12)
        height = max(50, self.source_canvas.winfo_height() - 12)
        image.thumbnail((width, height))
        if self._source_zoom > 1:
            image = image.resize((round(image.width * self._source_zoom), round(image.height * self._source_zoom)))
        self._source_image = ImageTk.PhotoImage(image, master=self.window)
        self.source_canvas.create_image(max(width, image.width) / 2, max(height, image.height) / 2, image=self._source_image)
        self.source_canvas.configure(scrollregion=(0, 0, max(width, image.width), max(height, image.height)))

    def _zoom_source(self, factor):
        self._source_zoom = min(4., max(1., self._source_zoom * factor))
        self._draw_source()

    def _draw_geometry(self):
        canvas = self.geometry_canvas
        canvas.delete('all')
        self._transform = None
        if not self.preview:
            return
        axis_x, axis_y = PROJECTIONS[self.projection.get()]
        xbounds = self.preview['bounds'][axis_x]
        ybounds = self.preview['bounds'][axis_y]
        width, height = max(100, canvas.winfo_width()), max(100, canvas.winfo_height())
        dx, dy = max(.5, xbounds[1] - xbounds[0]), max(.5, ybounds[1] - ybounds[0])
        scale = min((width - 60) / dx, (height - 65) / dy)
        center_x, center_y = sum(xbounds) / 2, sum(ybounds) / 2
        self._transform = (width / 2, height / 2, scale, center_x, center_y)
        def point(vertex):
            return (width / 2 + (vertex[axis_x] - center_x) * scale, height / 2 - (vertex[axis_y] - center_y) * scale)
        for component in self.preview['components']:
            selected = component['id'] == self.component.get()
            for a, b in component['edges']:
                canvas.create_line(*point(a), *point(b), fill='#275dad' if selected else '#bdc4cd', width=1.4 if selected else 1)
        axes = self.projection.get()
        canvas.create_text(8, 8, anchor='nw', text=f'{axes[0].upper()}/{axes[1].upper()} metres | {xbounds[0]:.2f}..{xbounds[1]:.2f} / {ybounds[0]:.2f}..{ybounds[1]:.2f}', fill='#334155')
        if self.preview['simplified']:
            canvas.create_text(8, height - 8, anchor='sw', text='Display simplified; saved geometry is unchanged.', fill='#9a3412')
        for correction in self.corrections:
            if correction['type'] in ('outline', 'opening') and correction['projection'] == self.projection.get():
                self._draw_polygon(correction['points_m'], '#d97706', closed=True)
        self._draw_polygon(self.draft_points, '#dc2626', closed=False)

    def _draw_polygon(self, points, colour, closed):
        if not self._transform:
            return
        ox, oy, scale, cx, cy = self._transform
        pixels = [(ox + (x - cx) * scale, oy - (y - cy) * scale) for x, y in points]
        for point in pixels:
            self.geometry_canvas.create_oval(point[0] - 3, point[1] - 3, point[0] + 3, point[1] + 3, fill=colour, outline=colour)
        if len(pixels) >= 2:
            line = pixels + ([pixels[0]] if closed else [])
            self.geometry_canvas.create_line(*[v for point in line for v in point], fill=colour, width=2)

    def _geometry_click(self, event):
        if not self._transform or self.correction_type.get() not in ('outline', 'opening'):
            return
        if len(self.draft_points) >= 4096:
            self._error('Correction polygon point budget reached.')
            return
        ox, oy, scale, cx, cy = self._transform
        self.draft_points.append([round(cx + (event.x - ox) / scale, 6), round(cy - (event.y - oy) / scale, 6)])
        self._review_changed()
        point = self.draft_points[-1]
        self.point_status.set(f'{len(self.draft_points)} trace points | latest ({point[0]:.3f}, {point[1]:.3f}) m in {self.projection.get().upper()} | Add correction to retain polygon')
        self._draw_geometry()

    def _add_exact_point(self):
        try:
            if self.correction_type.get() not in ('outline', 'opening'):
                raise ValueError('Exact polygon points apply to outline and opening corrections.')
            point = [float(value.strip()) for value in self.point_entry.get().split(',')]
            if len(point) != 2 or any(not math.isfinite(value) or abs(value) > 10000 for value in point):
                raise ValueError('Enter two finite projected metre coordinates within 10000 m.')
            if len(self.draft_points) >= 4096:
                raise ValueError('Correction polygon point budget reached.')
            self.draft_points.append(point)
            self._review_changed()
            self.point_status.set(f'{len(self.draft_points)} trace points | latest ({point[0]:.3f}, {point[1]:.3f}) m in {self.projection.get().upper()}')
            self._draw_geometry()
        except Exception as error:
            self._error(str(error))

    def _clear_trace(self):
        self.draft_points = []
        self._review_changed()
        self.point_status.set('Click generated geometry to trace a replacement polygon in local metres; source pixels are not registered automatically.')
        self._draw_geometry()

    def _undo_point(self):
        if self.draft_points:
            self.draft_points.pop()
            self._review_changed()
        self._draw_geometry()
        self.point_status.set(f'{len(self.draft_points)} trace points retained.')

    def add_correction(self):
        try:
            if not self.current_record:
                raise ValueError('Choose an original candidate first.')
            sha = self._source_labels.get(self.source_choice.get())
            source = self.session['resolved_sources'].get(sha)
            page = self.source_page.get()
            if not source or not 1 <= page <= source['pages']:
                raise ValueError('Bind a matching original PDF and choose an existing source page.')
            if self._displayed_source != (sha, page):
                raise ValueError('Show and verify the selected original source page before adding a correction.')
            kind = self.correction_type.get()
            annotation = {'type': kind, 'source_sha256': sha, 'source_page': page}
            if kind in ('outline', 'opening'):
                if len(self.draft_points) < 3:
                    raise ValueError('Trace at least three polygon points on the generated geometry preview.')
                from shapely.geometry import Polygon
                polygon = Polygon(self.draft_points)
                if not polygon.is_valid or polygon.area <= 1e-8:
                    raise ValueError('Trace a simple polygon with a nonzero area.')
                annotation.update(component_id=self.component.get(), projection=self.projection.get(), points_m=copy.deepcopy(self.draft_points))
            elif kind == 'dimension':
                value = float(self.dimension.get())
                if not math.isfinite(value) or not 0 < value <= 10000:
                    raise ValueError('Enter a positive finite dimension up to 10000 metres.')
                annotation.update(component_id=self.component.get(), value_m=value, axis=self.dimension_axis.get())
            elif kind == 'placement':
                translation = [float(v.strip()) for v in self.translation.get().split(',')]
                rotation = float(self.rotation.get())
                if len(translation) != 3 or any(not math.isfinite(v) or abs(v) > 10000 for v in translation) or not math.isfinite(rotation) or abs(rotation) > 360:
                    raise ValueError('Enter three finite XYZ offsets within 10000 m and a rotation within 360 degrees.')
                annotation.update(translation_m=translation, rotation_degrees=rotation)
            else:
                raise ValueError('Choose a supported correction type.')
            if len(self.corrections) >= 256:
                raise ValueError('Correction annotation budget reached.')
            self.corrections.append(annotation)
            self.last_error = None
            self.correction_list.insert('end', f"{kind}: {annotation.get('component_id', 'building')} | source page {page} | {sha[:12]}")
            self.last_report = None
            self.import_button.state(['disabled'])
            self._clear_trace()
            self.status.set('Correction added as a proposal. Save a draft or independently review the original candidate.')
        except Exception as error:
            self._error(str(error))

    def _remove_correction(self):
        selected = self.correction_list.curselection()
        if selected:
            index = selected[0]
            del self.corrections[index]
            self.correction_list.delete(index)
            self.last_report = None
            self._review_changed()
            self.import_button.state(['disabled'])
            self._draw_geometry()

    def save_draft(self):
        self._save(False)

    def save_decision(self):
        self._save(True)

    def _save(self, reviewed):
        try:
            from .desktop_review import save_review
            if self.pending:
                raise ValueError('Wait for the current preview or review operation before saving.')
            record = self.current_record
            if not record:
                raise ValueError('Open a review queue and choose a candidate first.')
            if self.draft_points:
                raise ValueError('Add or clear the current polygon trace before saving.')
            outcome = self.outcome.get() if reviewed else None
            if reviewed and outcome not in ('accepted', 'rejected'):
                raise ValueError('Choose an independently reviewed accepted or rejected outcome for the original candidate.')
            if reviewed and not self.review_reference.get().strip():
                raise ValueError('Supply the external review reference before saving a reviewed decision.')
            if reviewed and outcome == 'accepted' and self.corrections:
                raise ValueError('Corrections describe a replacement. Reject the original candidate or save a correction draft.')
            session = copy.deepcopy(self.session)
            corrections = copy.deepcopy(self.corrections)
            basis = self.review_basis.get() if reviewed else None
            reference = self.review_reference.get().strip() if reviewed else ''
            output = self.output_root / uuid.uuid4().hex
            revision = self._state_revision
            queue_pin = session['queue_sha256']
            candidate_pin = record['candidate_sha256']
            self.import_button.state(['disabled'])
            def saved(report):
                self.last_saved_report = report
                current = self.current_record
                if (revision != self._state_revision or not current
                        or self.session['queue_sha256'] != queue_pin
                        or current['candidate_sha256'] != candidate_pin):
                    self.status.set('Review saved for the previous edit state: ' + str(report['output_directory']))
                    return
                self.last_report = report
                self.status.set(('Reviewed original decision saved. ' if reviewed else 'Correction draft saved without training labels. ') + str(report['output_directory']))
                if reviewed and report.get('feedback_path') and self.on_feedback:
                    self.import_button.state(['!disabled'])
            self._background(lambda: save_review(session, building_id=record['building_id'], candidate_sha256=record['candidate_sha256'], outcome=outcome, review_basis=basis, review_reference=reference, corrections=corrections, output_directory=output), saved, 'Saving immutable source-linked review...')
        except Exception as error:
            self._error(str(error))

    def import_feedback(self):
        try:
            if not self.on_feedback or not self.last_report or not self.last_report.get('feedback_path'):
                raise ValueError('Save a reviewed decision before importing feedback.')
            self.on_feedback(self.last_report['feedback_path'])
            self.import_button.state(['disabled'])
            self.status.set('Reviewed feedback submitted to persistent learning. Existing model promotion checks still apply.')
        except Exception as error:
            self._error(str(error))

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self._token:
            self.window.after_cancel(self._token)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.window.destroy()


def smoke_test(output):
    """Exercise the actual source preview, correction click and draft save UI.

    The fixture is explicitly synthetic. This proves the frozen window can
    operate; it does not contribute real review labels or accuracy evidence.
    """
    import json
    import time
    import tkinter as tk
    from .desktop_review_presets import prepare_demo
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {'version': 'desktop-review-ui-smoke-v1', 'status': 'failed',
              'dataset_kind': 'synthetic', 'training_labels_generated': 0,
              'physical_acceptance': False}
    root = None
    review = None
    deadline = time.monotonic() + 45
    def wait_for(predicate):
        while time.monotonic() < deadline:
            root.update()
            if predicate():
                return
            if review.last_error:
                raise ValueError(review.last_error)
            time.sleep(.01)
        raise TimeoutError('Review UI smoke exceeded its 45 second deadline')
    def reveal(widget):
        root.update_idletasks()
        viewport = review.viewport
        bbox = viewport.bbox('all')
        if not bbox:
            raise ValueError('Review scrollable content is unavailable')
        top = widget.winfo_rooty() - viewport.winfo_rooty() + viewport.canvasy(0)
        viewport.yview_moveto(max(0., (top - 30) / max(1, bbox[3])))
        root.update()
        wy = widget.winfo_rooty()
        vy = viewport.winfo_rooty()
        if not widget.winfo_ismapped() or wy < vy or wy + widget.winfo_height() > vy + viewport.winfo_height():
            raise ValueError('Review control is not reachable by scrolling: ' + str(widget))
    try:
        preset = prepare_demo(output/'demo')
        root = tk.Tk()
        root.withdraw()
        review = ReviewWindow(root, output/'reviews')
        review.window.geometry('940x650+10+10')
        review.load_queue(preset['queue_path'], batch_path=preset['batch_path'], source_paths=preset['source_paths'])
        wait_for(lambda: review.pending == 0 and review.preview is not None and review._displayed_source is not None)
        if not review.source_canvas.find_all() or not review.geometry_canvas.find_all():
            raise ValueError('Source or geometry canvas did not display its actual content')
        report.update(source_page_rendered=True, geometry_displayed=True,
                      source_and_geometry_frames='separate',
                      geometry_edges=review.preview['edge_count'])
        try:
            from PIL import ImageGrab
            root.update_idletasks()
            box = (review.window.winfo_rootx(), review.window.winfo_rooty(),
                   review.window.winfo_rootx()+review.window.winfo_width(),
                   review.window.winfo_rooty()+review.window.winfo_height())
            ImageGrab.grab(bbox=box).save(output/'review-source.png')
            report['source_screenshot'] = 'review-source.png'
        except Exception as error:
            report['screenshot_reason'] = str(error)
        ox, oy, scale, cx, cy = review._transform
        for x, y in ((.5, .5), (3., .5), (3., 2.5), (.5, 2.5)):
            review.geometry_canvas.event_generate('<Button-1>', x=round(ox+(x-cx)*scale), y=round(oy-(y-cy)*scale))
            root.update()
        if len(review.draft_points) != 4:
            raise ValueError('Actual geometry clicks did not retain four local-metre points')
        reveal(review.add_button)
        review.add_button.invoke()
        if len(review.corrections) != 1:
            raise ValueError(review.last_error or 'The correction button did not retain the polygon')
        for widget in (review.candidate_picker, review.source_picker, review.add_button,
                       review.draft_button, review.save_button, review.import_button):
            reveal(widget)
        report['controls_reachable_by_scrolling'] = True
        reveal(review.draft_button)
        review.draft_button.invoke()
        wait_for(lambda: review.pending == 0 and review.last_report is not None)
        saved = review.last_report
        if saved.get('status') != 'correction_draft_saved' or saved.get('feedback_path'):
            raise ValueError('A correction draft unexpectedly produced reviewed feedback')
        if not Path(saved['corrections_path']).is_file():
            raise ValueError('The correction sidecar was not written')
        if 'disabled' not in review.import_button.state():
            raise ValueError('A correction draft must not enable training-feedback import')
        report.update(status='passed', draft_saved=True, feedback_import_enabled=False,
                      corrections_path=str(saved['corrections_path']),
                      window_size=[review.window.winfo_width(), review.window.winfo_height()])
        try:
            from PIL import ImageGrab
            box = (review.window.winfo_rootx(), review.window.winfo_rooty(),
                   review.window.winfo_rootx()+review.window.winfo_width(),
                   review.window.winfo_rooty()+review.window.winfo_height())
            ImageGrab.grab(bbox=box).save(output/'review-controls.png')
            report['controls_screenshot'] = 'review-controls.png'
        except Exception:
            pass
        retained_corrections = copy.deepcopy(review.corrections)
        saved_directory = saved['output_directory']
        review.close()
        root.destroy()
        root = tk.Tk()
        root.withdraw()
        review = ReviewWindow(root, output/'reviews')
        review.window.geometry('940x650+10+10')
        review.load_saved_review(saved_directory)
        wait_for(lambda: review.pending == 0 and review.preview is not None and review._displayed_source is not None)
        if review.corrections != retained_corrections or review.last_report is not None:
            raise ValueError('Fresh review window did not restore the saved correction draft')
        if review.outcome.get() != 'unreviewed' or 'disabled' not in review.import_button.state():
            raise ValueError('Resuming a correction draft unexpectedly enabled reviewed feedback')
        report['saved_draft_reopened_in_fresh_window'] = True
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
    finally:
        if review:
            review.close()
        if root:
            root.destroy()
        (output/'review-ui-smoke.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report
