"""Actual desktop correction -> managed worker -> regenerated world check."""
import json
from pathlib import Path
import time


def run(output):
    import tkinter as tk
    from unittest.mock import patch
    from .desktop_app import DesktopWindow
    output=Path(output).expanduser().resolve()
    if output.exists():raise ValueError('A fresh desktop correction test directory is required')
    output.mkdir(parents=True)
    receipt={'status':'failed','dataset_kind':'synthetic','training_labels_generated':0,
             'physical_acceptance':False,'real_world_accuracy_established':False}
    root=None;desktop=None;errors=[];deadline=time.monotonic()+120
    def wait_for(predicate):
        while time.monotonic()<deadline:
            root.update()
            if errors:raise RuntimeError(errors[-1])
            for job in desktop.last_snapshot.get('jobs',[]):
                if job['status']=='failed':raise RuntimeError(job.get('error') or job['message'])
            if predicate():return
            time.sleep(.03)
        raise TimeoutError('The source/correction/world workflow exceeded its test deadline')
    def capture(window,name):
        try:
            from PIL import ImageGrab
            window.update_idletasks()
            ImageGrab.grab(bbox=(window.winfo_rootx(),window.winfo_rooty(),window.winfo_rootx()+window.winfo_width(),window.winfo_rooty()+window.winfo_height())).save(output/name)
            return name
        except Exception as error:
            receipt['screenshot_reason']=str(error)
            return None
    def reveal(review,widget):
        root.update_idletasks();viewport=review.viewport;bounds=viewport.bbox('all')
        top=widget.winfo_rooty()-viewport.winfo_rooty()+viewport.canvasy(0)
        viewport.yview_moveto(max(0.,(top-30)/max(1,bounds[3])));root.update()
        x=widget.winfo_rootx()-viewport.winfo_rootx();y=widget.winfo_rooty()-viewport.winfo_rooty()
        if not widget.winfo_ismapped() or x<0 or y<0 or x+widget.winfo_width()>viewport.winfo_width() or y+widget.winfo_height()>viewport.winfo_height():
            raise AssertionError('A regeneration control is clipped or unreachable')
    try:
        root=tk.Tk();desktop=DesktopWindow(root,output/'memory',workers=2,memory_budget_mb=2048)
        desktop._error=lambda error:errors.append(str(error))
        root.geometry('1000x720+10+10')
        desktop._prepare_review('correction_demo')
        wait_for(lambda:desktop.review_windows and desktop.review_windows[-1].pending==0
                 and desktop.review_windows[-1].preview is not None and desktop.review_windows[-1]._displayed_source is not None)
        original=desktop.review_windows[-1]
        original.window.geometry('940x650+20+20');root.update()
        receipt['original_screenshot']=capture(original.window,'original-candidate.png')
        original_hash=original.current_record['candidate_sha256']
        original.correction_type.set('dimension');original.dimension_axis.set('x');original.dimension.set('8')
        original.add_button.invoke()
        if original.last_error:raise ValueError(original.last_error)
        original.draft_button.invoke()
        wait_for(lambda:original.pending==0 and original.last_report is not None)
        if 'disabled' in original.regenerate_button.state():raise ValueError('Saving a correction did not enable explicit regeneration')
        reveal(original,original.regenerate_button)
        receipt['controls_screenshot']=capture(original.window,'regeneration-controls.png')
        original.regenerate_button.invoke()
        wait_for(lambda:len(desktop.review_windows)>1 and desktop.review_windows[-1].pending==0
                 and desktop.review_windows[-1].preview is not None and desktop.review_windows[-1]._displayed_source is not None)
        revised=desktop.review_windows[-1]
        revised.window.geometry('940x650+20+20');root.update()
        if revised.last_error:raise ValueError(revised.last_error)
        candidate=revised.current_record['candidate']
        width=max(p[0] for p in candidate['spec']['components'][0]['geometry']['profile'])
        if width!=8 or revised.current_record['candidate_sha256']==original_hash:
            raise AssertionError('The new candidate does not contain the requested changed geometry')
        if any(candidate['gates'].values()) or revised.current_record['outcome'] is not None:
            raise AssertionError('Regeneration bypassed independent candidate review')
        job=next(j for j in desktop.last_snapshot['jobs'] if j['kind']=='regenerate_corrections')
        benchmark=job['result']['benchmark']
        if benchmark['status']!='measured' or benchmark['before']['cases_within_thresholds']!=0 or benchmark['after']['cases_within_thresholds']!=1:
            raise AssertionError('The actual regenerated candidate did not improve against the fixed synthetic drawing reference')
        world=Path(job['result']['corrected_world_path'])
        if not world.is_file():raise AssertionError('The actual corrected world package is missing')
        if 'all written blocks' not in job['result']['corrected_native']['world']['round_trip_validation']:
            raise AssertionError('Corrected native world readback was not verified')
        memory=desktop.last_snapshot['memory']
        if memory['feedback_records'] or memory['checkpoints']:raise AssertionError('The workflow created training labels or promoted a model')
        desktop.jobs.selection_set(job['id']);desktop._show_details()
        with patch('voxel_mapper.desktop_app.os.startfile',create=True) as opened:
            desktop._open_job_output('park.mcworld');desktop._open_job_output('placement-comparison.svg')
        if errors:raise RuntimeError(errors[-1])
        if opened.call_count not in (0,2):raise AssertionError('The world/comparison actions used an unexpected output')
        receipt['screenshot']=capture(revised.window,'corrected-candidate.png')
        receipt.update(status='passed',source_preview_rendered=True,explicit_draft_save=True,explicit_regenerate_button=True,
            original_width_m=6,corrected_width_m=width,original_candidate_sha256=original_hash,
            corrected_candidate_sha256=revised.current_record['candidate_sha256'],new_candidate_requires_review=True,
            native_world_saved_and_read_back=True,world_and_comparison_actions=True,regeneration_control_reachable=True,
            managed_peak_memory_mb=job['peak_memory_mb'],corrected_world_path=str(world),
            benchmark_status=benchmark['status'],reference_cases_passing_before=0,reference_cases_passing_after=1)
    except Exception as error:receipt['error']=str(error)
    finally:
        if desktop:desktop.close()
        elif root:root.destroy()
        (output/'correction-ui-smoke.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return receipt
