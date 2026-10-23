"""Retained real-area presets, portable input bundles and bounded PDF recovery."""
from concurrent.futures import CancelledError
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import time
from urllib.parse import urlparse

VERSION = 'desktop-area-pilots-v1'
MAX_FILE_BYTES = 64_000_000
MAX_BUNDLE_BYTES = 256_000_000
PRESETS = (
    {'id': 'alton-terrain-paths', 'label': 'Alton terrain and paths - included offline',
     'job': 'examples/alton-world-pilot-ostn15-job.json',
     'scope': 'Real retained EA terrain and mapped paths. Planning buildings remain awaiting evidence.'},
    {'id': 'wicker-plazas-a', 'label': 'Wicker building and plazas - study A',
     'job': 'examples/wicker-planning-paving-joins-a-job.json',
     'scope': 'Provisional building, paths and three planning plazas. Orientation A, floor and materials remain estimates; four original PDFs are required.'},
    {'id': 'wicker-plazas-b', 'label': 'Wicker building and plazas - study B',
     'job': 'examples/wicker-planning-paving-joins-b-job.json',
     'scope': 'The same provisional study with orientation B. Neither orientation is physically accepted; four original PDFs are required.'},
)


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _json(path):
    path = Path(path)
    if path.stat().st_size > 16_000_000:
        raise ValueError('Area JSON byte budget exceeded')
    return json.loads(path.read_text(encoding='utf-8'))


def _write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _inside(root, relative):
    if not isinstance(relative, str) or '\\' in relative:
        raise ValueError('Portable area asset path required')
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or '..' in parsed.parts or ':' in relative:
        raise ValueError('Area asset path must stay inside its bundle')
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Area asset escapes its bundle')
    return path


def _descriptors(value):
    if isinstance(value, dict):
        if 'file' in value and 'sha256' in value:
            yield value
        else:
            for item in value.values():
                yield from _descriptors(item)
    elif isinstance(value, list):
        for item in value:
            yield from _descriptors(item)


def compile_manifest(repository):
    """Collect only the files consumed by the existing pilot contract."""
    root = Path(repository).resolve()
    sources = {row['sha256']: {'url':row['url'],'transport_url':row['transport_url']} for row in _json(root/'examples/wicker-evidence-acquisition-catalogue.json')['entries']}
    paving = _json(root/'docs/evidence/planning-surfaces/source-record.json')
    # Public attachment transport fallback is bound to the same exact PDF hash.
    sources[paving['document_sha256']] = {'url':paving['source_url'], 'transport_url':paving['source_url'].replace('https://','http://',1)}
    presets = []
    for preset in PRESETS:
        files = {}
        def add(path, expected):
            path = Path(path).resolve()
            relative = path.relative_to(root).as_posix()
            if not re.fullmatch('[0-9a-f]{64}', expected):
                raise ValueError('Pinned area asset hash required')
            if relative in files and files[relative]['sha256'] != expected:
                raise ValueError('Conflicting area asset pins')
            external = relative.startswith('retained-source-input/')
            if external and (path.suffix.lower() != '.pdf' or expected not in sources):
                raise ValueError('Unregistered external area source')
            if not external and (not path.is_file() or _sha(path) != expected):
                raise ValueError('Missing or changed retained area asset: ' + relative)
            files[relative] = {'path': relative, 'sha256': expected, 'external': external}
            if external:
                files[relative].update(sources[expected])
            return path
        job_path = root/preset['job']
        add(job_path, _sha(job_path))
        job = _json(job_path)
        for descriptor in _descriptors(job):
            add(job_path.parent/descriptor['file'], descriptor['sha256'])
        config_path = job_path.parent/job['config']['file']
        config = _json(config_path)
        for key in ('terrain', 'surface', 'surface_fallback', 'bathymetry'):
            if config.get(key):
                add(config_path.parent/config[key]['path'], config[key]['sha256'])
        review_path = job_path.parent/job['planning_review']['file']
        for descriptor in _descriptors(_json(review_path)):
            add(review_path.parent/descriptor['file'], descriptor['sha256'])
        presets.append({**preset, 'files': sorted(files.values(), key=lambda row: row['path'])})
    return {'version': VERSION, 'presets': presets}


def build_bundle(repository, destination):
    """Keep the retained layout so all existing nested hashes remain valid."""
    root, destination = Path(repository).resolve(), Path(destination)
    if destination.exists():
        raise ValueError('Build area data into a fresh directory')
    manifest = compile_manifest(root)
    destination.mkdir(parents=True)
    copied = set()
    total = 0
    for preset in manifest['presets']:
        for row in preset['files']:
            if row['external'] or row['path'] in copied:
                continue
            source = _inside(root, row['path'])
            total += source.stat().st_size
            if source.stat().st_size > MAX_FILE_BYTES or total > MAX_BUNDLE_BYTES:
                raise ValueError('Area data bundle exceeds its byte budget')
            target = _inside(destination, row['path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if _sha(target) != row['sha256']:
                raise ValueError('Area data changed while bundling')
            copied.add(row['path'])
    _write(destination/'manifest.json', manifest)
    return manifest


def bundle():
    if getattr(sys, 'frozen', False):
        root = Path(sys._MEIPASS)/'area-pilots'
        manifest = _json(root/'manifest.json')
    else:
        root = Path(__file__).resolve().parent.parent
        manifest = compile_manifest(root)
    if manifest.get('version') != VERSION:
        raise ValueError('Unsupported desktop area bundle')
    return root, manifest


def _find_originals(directory, wanted, cancelled):
    found = {}
    if not directory or not wanted:
        return found
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Choose an existing retained-source folder')
    entries = total = 0
    for folder, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = [d for d in directories if not d.startswith('.') and not (Path(folder)/d).is_symlink()]
        entries += len(directories) + len(filenames)
        if entries > 4096:
            raise ValueError('Choose a smaller source folder (at most 4,096 entries)')
        for name in filenames:
            if cancelled():
                raise CancelledError()
            path = Path(folder)/name
            if path.suffix.lower() != '.pdf' or path.is_symlink():
                continue
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                continue
            total += size
            if total > MAX_BUNDLE_BYTES:
                raise ValueError('Source search exceeds 256 MB; choose a smaller folder')
            pin = _sha(path)
            if pin in wanted:
                found[pin] = path
                if wanted <= found.keys():
                    return found
    return found


def _download_once(row, url, target, cancelled):
    import requests
    parsed = urlparse(url)
    if (parsed.scheme not in ('http','https') or parsed.hostname != 'publicaccess.staffsmoorlands.gov.uk'
            or parsed.port is not None or parsed.username is not None or parsed.password is not None
            or parsed.path != '/portal/servlets/AttachmentShowServlet'):
        raise ValueError('Registered council attachment required')
    partial = target.with_suffix('.partial')
    started = time.monotonic()
    try:
        with requests.get(url, stream=True, allow_redirects=False, timeout=(10, 15)) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError('Council attachment did not return a complete PDF')
            total = 0
            with partial.open('wb') as stream:
                for chunk in response.iter_content(65536):
                    if cancelled():
                        raise CancelledError()
                    total += len(chunk)
                    if total > MAX_FILE_BYTES or time.monotonic() - started > 45:
                        raise ValueError('Council PDF download exceeded its work budget')
                    stream.write(chunk)
        with partial.open('rb') as stream:
            if stream.read(5) != b'%PDF-':
                raise ValueError('Council attachment is not an original PDF')
        if _sha(partial) != row['sha256']:
            raise ValueError('Council original checksum differs from the retained source')
        partial.replace(target)
        return {'url':url,'status':'checksum_verified','bytes':total,'sha256':row['sha256']}
    finally:
        partial.unlink(missing_ok=True)


class AreaDownloadError(ValueError):
    def __init__(self, attempts):
        self.attempts=attempts
        super().__init__('; '.join(a['error'] for a in attempts))


def _download(row, target, cancelled):
    canonical=row['url']
    if not canonical.startswith('https://'):
        raise ValueError('Registered HTTPS council attachment required')
    urls=[canonical]
    transport=row.get('transport_url')
    if transport:
        if transport!=canonical.replace('https://','http://',1):
            raise ValueError('Council fallback must name the same pinned public attachment')
        urls.append(transport)
    attempts=[]
    for url in urls:
        try:
            result=_download_once(row,url,target,cancelled)
            attempts.append(result)
            return attempts
        except CancelledError:
            raise
        except Exception as error:
            attempt={'url':url,'status':'unavailable','error':str(error)}
            response=getattr(error,'response',None)
            if response is not None:attempt['status_code']=response.status_code
            attempts.append(attempt)
    raise AreaDownloadError(attempts)


def run(preset_id, output, *, evidence_directory=None, download_missing=False,
        cache_directory=None, cancelled=lambda: False, progress=lambda value: None):
    """Resolve evidence first; never replace missing planning sources with guesses."""
    if type(download_missing) is not bool:
        raise ValueError('Download setting must be boolean')
    root, manifest = bundle()
    preset = next((p for p in manifest['presets'] if p['id'] == preset_id), None)
    if preset is None:
        raise ValueError('Choose a registered area preset')
    output = Path(output).resolve()
    inputs = output.with_name('area-inputs')
    if output.exists() or inputs.exists():
        raise ValueError('Area generation requires fresh output and input directories')
    inputs.mkdir(parents=True)
    cache = Path(cache_directory) if cache_directory else output.with_name('source-cache')
    cache.mkdir(parents=True, exist_ok=True)
    external = [row for row in preset['files'] if row['external']]
    originals = {}
    for row in external:
        path = cache/(row['sha256']+'.pdf')
        if path.is_file() and path.stat().st_size <= MAX_FILE_BYTES and _sha(path) == row['sha256']:
            originals[row['sha256']] = path
    wanted = {row['sha256'] for row in external} - originals.keys()
    originals.update(_find_originals(evidence_directory, wanted, cancelled))
    report = {'version': VERSION, 'preset': preset_id, 'scope': preset['scope'],
              'source_status': [], 'training_labels_generated': 0, 'physical_acceptance_inferred': False}
    report_path = inputs/'area-source-report.json'
    total = 0
    missing = []
    for index, row in enumerate(preset['files']):
        if cancelled():
            raise CancelledError()
        target = _inside(inputs, row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        source = originals.get(row['sha256']) if row['external'] else _inside(root, row['path'])
        entry = {'file': row['path'], 'sha256': row['sha256'], 'status': 'retained'}
        if row['external']:
            entry['url'] = row['url']
            if source is None and download_missing:
                try:
                    progress({'progress': .02, 'message': 'Gathering original council PDF'})
                    candidate = cache/(row['sha256']+'.pdf')
                    entry['download_attempts'] = _download(row, candidate, cancelled)
                    source = candidate
                    entry['status'] = 'downloaded_and_checksum_verified'
                except (OSError, ValueError) as error:
                    entry.update(status='unavailable', error=str(error), download_attempts=getattr(error,'attempts',[]))
                except Exception as error:
                    # Network failures are diagnostics; cancellation propagates.
                    if isinstance(error, CancelledError):
                        raise
                    entry.update(status='unavailable', error=str(error), download_attempts=getattr(error,'attempts',[]))
            if source is None:
                entry['status'] = 'awaiting_original_pdf'
                missing.append(row['sha256'])
                report['source_status'].append(entry)
                _write(report_path, report)
                continue
        if not source.is_file() or source.stat().st_size > MAX_FILE_BYTES or _sha(source) != row['sha256']:
            raise ValueError('Area source changed: ' + row['path'])
        total += source.stat().st_size
        if total > MAX_BUNDLE_BYTES:
            raise ValueError('Area inputs exceed the 256 MB byte budget')
        shutil.copyfile(source, target)
        if _sha(target) != row['sha256']:
            raise ValueError('Area source changed while copying: ' + row['path'])
        if row['external'] and source.parent != cache:
            cached = cache/(row['sha256']+'.pdf')
            shutil.copyfile(target, cached)
        report['source_status'].append(entry)
        progress({'progress': .04 + .06*(index+1)/len(preset['files']), 'message': 'Checking retained area evidence'})
    report['status'] = 'awaiting_original_pdfs' if missing else 'inputs_ready'
    _write(report_path, report)
    if missing:
        raise ValueError(f'{len(missing)} original planning PDFs unavailable. Choose the retained-source folder or enable council downloads. Details: {report_path}')
    if cancelled():
        raise CancelledError()
    from .world_pilot import run as generate
    progress({'progress': .12, 'message': 'Generating area and checking saved-world geometry'})
    result = generate(_inside(inputs, preset['job']), output)
    details = {'preset': preset_id, 'scope': preset['scope'], 'source_report': str(report_path),
                              'source_report_sha256': _sha(report_path),
                              'pilot_report': str(output/'pilot-report.json'),
                              'pilot_report_sha256': _sha(output/'pilot-report.json'),
                              'world_file': str(output/'park.mcworld') if result.get('world') else None,
                              'comparison_file': str(output/'placement-comparison.svg'),
                              'training_labels_generated': 0}
    _write(output/'area-launch-report.json', details)
    # Large native routes and meshes remain on disk, not in every GUI poll and
    # SQLite job snapshot on the 6 GB profile.
    summary = {key:result[key] for key in ('version','name','status','bbox','world','readiness','generated_voxel_records_by_kind')}
    summary.update(desktop_area=details,issue_count=len(result.get('issues',[])))
    return summary
