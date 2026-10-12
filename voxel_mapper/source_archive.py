"""Bounded reads of checksum-pinned original evidence; never extract ZIP paths."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import uuid
from urllib.parse import urlparse
import zipfile

MAX_ARCHIVE_BYTES = 2_000_000_000
MAX_MEMBERS = 20_000
MAX_METADATA_BYTES = 8_000_000
MAX_PDF_BYTES = 64_000_000
MAX_HTML_BYTES = 2_000_000
MAX_RECORDS = 10_000


def pinned_sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Pinned SHA256 required')
    return value


def safe_member(name):
    if (not isinstance(name, str) or not name or len(name) > 512
            or '\\' in name or ':' in name or '\x00' in name
            or name.startswith('/') or any(p in ('', '.', '..') for p in name.rstrip('/').split('/'))):
        raise ValueError('Unsafe archive member name')
    for part in name.rstrip('/').split('/'):
        if (part.endswith((' ', '.')) or any(ord(c) < 32 for c in part)
                or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)):
            raise ValueError('Unsafe archive member name on Windows')
    return name


@contextmanager
def checked_archive(archive, expected_sha256):
    """Use the same open file for the outer pin and ZIP reads."""
    pinned_sha(expected_sha256)
    with Path(archive).open('rb') as stream:
        if stream.seek(0, 2) > MAX_ARCHIVE_BYTES:
            raise ValueError('Archive compressed-byte budget exceeded')
        stream.seek(0)
        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected_sha256:
            raise ValueError('Archive checksum mismatch')
        stream.seek(0)
        with zipfile.ZipFile(stream) as source:
            members = source.infolist()
            if len(members) > MAX_MEMBERS:
                raise ValueError('Archive member budget exceeded')
            names = set()
            total = 0
            for item in members:
                # ZipInfo normalizes backslashes on Windows. Check the stored
                # name as well, so portable replay cannot hide an unsafe alias.
                safe_member(item.orig_filename)
                safe_member(item.filename)
                key = item.filename.rstrip('/').casefold()
                if key in names:
                    raise ValueError('Archive duplicate member names')
                names.add(key)
                mode = stat.S_IFMT(item.external_attr >> 16)
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError('Archive links/special files are not supported')
                if item.flag_bits & 1 or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError('Encrypted/unsupported archive compression')
                total += item.file_size
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError('Archive expanded-byte budget exceeded')
            yield source, {m.filename: m for m in members}


def read_member(source, item, limit, sha=None):
    if item.is_dir() or item.file_size > limit:
        raise ValueError('Archive member byte budget exceeded')
    with source.open(item) as stream:
        data = stream.read(limit + 1)
    if len(data) != item.file_size or len(data) > limit:
        raise ValueError('Archive member byte budget/size mismatch')
    if sha is not None and hashlib.sha256(data).hexdigest() != pinned_sha(sha):
        raise ValueError('Retained source checksum mismatch: ' + item.filename)
    return data


def load_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    try:
        def nonfinite(value):
            raise ValueError('Nonfinite JSON number')
        return json.loads(data, object_pairs_hook=unique, parse_constant=nonfinite)
    except (RecursionError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid bounded JSON') from error


def official_url(value, hosts):
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError('Official HTTPS URL required')
    parsed = urlparse(value)
    if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment):
        raise ValueError('Source URL outside declared HTTPS portals')
    return parsed


def pdf_records(data, hosts, *, allow_unpinned=False):
    if not isinstance(data, dict) or not isinstance(data.get('entries'), list) or len(data['entries']) > MAX_RECORDS:
        raise ValueError('Bounded archive catalogue required')
    for record in data['entries']:
        if not isinstance(record, dict):
            raise ValueError('Catalogue record must be an object')
        parsed = official_url(record.get('url'), hosts)
        sha = record.get('sha256')
        if sha is None and allow_unpinned and not record.get('file'):
            if record.get('transport_url'):
                raise ValueError('Pinned PDF required for retained transport metadata')
            continue
        pinned_sha(sha)
        if record.get('file') != f'files/{sha}.pdf':
            raise ValueError('Pinned content-addressed PDF member required')
        transport = record.get('transport_url')
        if transport:
            alternate = urlparse(transport)
            if (alternate.scheme not in ('http', 'https') or alternate.hostname != parsed.hostname
                    or alternate.port not in (None, 80 if alternate.scheme == 'http' else 443)
                    or alternate.username or alternate.password or alternate.fragment
                    or alternate.path != parsed.path or alternate.query != parsed.query):
                raise ValueError('Transport must name the same declared official resource')
    return data['entries']


def application_records(data, hosts, *, allow_unpinned=False):
    if not isinstance(data, dict) or not isinstance(data.get('applications'), list) or len(data['applications']) > MAX_RECORDS:
        raise ValueError('Bounded application catalogue required')
    for record in data['applications']:
        if not isinstance(record, dict) or not isinstance(record.get('reference'), str) or not record['reference']:
            raise ValueError('Application reference required')
        official_url(record.get('url'), hosts)
        sha = record.get('cached_page_sha256')
        if sha is None and allow_unpinned and not record.get('cached_page'):
            continue
        pinned_sha(sha)
        if record.get('cached_page') != f'files/{sha}.html':
            raise ValueError('Pinned content-addressed application HTML member required')
    return data['applications']


def retain(root, member, data, sha):
    """Write only a prevalidated member, rejecting escaping local links."""
    safe_member(member)
    root = Path(root).resolve()
    target = root.joinpath(*PurePosixPath(member).parts)
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError('Retained target escapes corpus or is a link')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == len(data):
        with target.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() == sha:
                return False
    temporary = target.with_suffix('.' + uuid.uuid4().hex + '.partial')
    try:
        if hashlib.sha256(data).hexdigest() != pinned_sha(sha):
            raise ValueError('Retained source changed during import')
        temporary.write_bytes(data)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return True
