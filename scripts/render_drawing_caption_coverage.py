"""Standalone original-sheet review of caption coverage and section candidates."""
import argparse
import base64
import json
from pathlib import Path

import pymupdf

from voxel_mapper.generation_cycles import file_hash


def render(evidence, source_catalogue, source_directory, output, section_review=None):
    evidence, source_catalogue, source_directory, output = map(Path,
        (evidence, source_catalogue, source_directory, output))
    raw = (evidence / 'drawing-caption-coverage.json').read_bytes(); report = json.loads(raw)
    assert file_hash(source_catalogue) == report['contract']['source_catalogue_sha256']
    entries = json.loads(source_catalogue.read_text())['entries']; sources = []
    for entry in entries:
        sources.append({'sha256': entry['sha256'], 'label': entry.get('title', entry['sha256']), 'kind': 'caption_source'})
    sections = json.loads(Path(section_review).read_text()) if section_review else []
    for record in sections:
        sources.append({'sha256': record['sha256'], 'label': record['label'], 'kind': 'site_source',
                        'section_inspection': record['page']})
    if len(sources) > 32: raise ValueError('Bounded source review required')
    for source in sources:
        path = source_directory / (source['sha256'] + '.pdf')
        if file_hash(path) != source['sha256']: raise ValueError('Original PDF changed')
        with pymupdf.open(path) as doc:
            if len(doc) != 1: raise ValueError('Single-page source review required')
            page = doc[0]; scale = 1800 / max(page.rect.width, page.rect.height)
            png = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes('png')
        import hashlib
        source.update(png='data:image/png;base64,' + base64.b64encode(png).decode(),
                      png_sha256=hashlib.sha256(png).hexdigest())
    payload = {'raw_json_base64': base64.b64encode(raw).decode(), 'sources': sources}
    data = json.dumps(payload).replace('<', '\\u003c')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Drawing source coverage</title>
<style>body{font:16px system-ui;max-width:1400px;margin:24px auto;padding:0 20px;color:#172b36;background:#f3f6f7}h1{font-size:27px}button,select{font:inherit;padding:8px}table{border-collapse:collapse;width:100%;background:white;margin:18px 0}th,td{text-align:left;border:1px solid #bbc9ce;padding:9px}img{width:100%;background:white;border:1px solid #bbc9ce}pre{white-space:pre-wrap;background:white;padding:15px}.note{background:#fff2d6;padding:14px}code{font-size:13px}#identity{overflow-wrap:anywhere}</style>
<h1>Drawing source coverage</h1><p id="summary"></p>
<p class="note">Caption matches locate source labels. Artwork assignment, scale, physical correspondence and shared-cap closure remain unresolved. Original reference visibility/identity holds are retained. No geometry is generated.</p>
<button id="download">Download exact evidence JSON</button>
<table><thead><tr><th>Roof source reference</th><th>Caption lookup</th><th>Prior measurement lookup</th><th>Next requirement</th></tr></thead><tbody id="links"></tbody></table>
<label>Original sheet <select id="source"></select></label><p id="identity"></p><img id="sheet" alt="Original planning sheet"><pre id="detail"></pre>
<script type="application/json" id="data">PAYLOAD</script><script>
const packed=JSON.parse(document.getElementById('data').textContent);
const bytes=Uint8Array.from(atob(packed.raw_json_base64),c=>c.charCodeAt(0));
const report=JSON.parse(new TextDecoder().decode(bytes));
const summary=document.getElementById('summary');summary.textContent=`${report.counts.unique_caption_links} exact caption links; ${report.counts.missing_captions} missing captions; ${report.counts.held_source_references} held references. ${report.counts.captions} original captions across ${report.counts.source_documents} architectural PDFs.`;
const links=document.getElementById('links');
for(const row of report.reference_links){const tr=document.createElement('tr');for(const value of [row.target_view_key_candidate?.join('/')||'Visibility or identity held',row.status,row.previous_measurement_link?.status||'Not evaluated',row.next_requirement]){const td=document.createElement('td');td.textContent=value;tr.append(td)}links.append(tr)}
const select=document.getElementById('source'),sheet=document.getElementById('sheet');
for(const [i,s] of packed.sources.entries()){const o=document.createElement('option');o.value=i;o.textContent=s.label;select.append(o)}
function draw(){const s=packed.sources[Number(select.value)];sheet.src=s.png;document.getElementById('identity').textContent=`Original PDF SHA-256: ${s.sha256}`;
const p=report.pages.find(p=>p.document_sha256===s.sha256);
document.getElementById('detail').textContent=s.kind==='site_source'?JSON.stringify({notice:'Site section/text candidates only. Overlapping title text can be hidden beneath later paint. Unassigned numeric labels do not identify physical components.',inspection:s.section_inspection},null,2):JSON.stringify(p.captions.map(c=>({caption:c.caption,key:c.source_caption_key_candidate||null,status:c.status,artwork_assignment_verified:c.artwork_assignment_verified})),null,2)}
select.onchange=draw;draw();
document.getElementById('download').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([bytes],{type:'application/json'}));a.download='drawing-caption-coverage.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
document.body.dataset.ready='true';
</script></html>'''.replace('PAYLOAD', data)
    output.write_text(page)
    return {'output': str(output), 'source_pages': len(sources), 'evidence_sha256': file_hash(evidence / 'drawing-caption-coverage.json')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('evidence', 'source-catalogue', 'source-directory', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--section-review', type=Path)
    print(json.dumps(render(**vars(parser.parse_args()))))
