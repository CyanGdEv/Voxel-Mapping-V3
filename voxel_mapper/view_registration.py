"""Auditable image correspondences for unregistered views; no chained georefs."""
import hashlib
import copy
import io
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image

from .recover_paving_georef import load_reference_mosaic


def matched_georef(reference_transform, matrix):
    """OpenCV index-centre coordinates to the raster pixel-corner convention."""
    from affine import Affine
    return reference_transform*Affine.translation(.5,.5)*Affine(*np.asarray(matrix).ravel())*Affine.translation(-.5,-.5)


def fit_correspondences(query, target, shape, *, tolerance=1., minimum=24):
    """Fit on spatial control cells; test held-out cells without inlier selection.

    Units are target pixels. Checkpoints share the image lineage and are not an
    independent geographic survey. A good fit remains a candidate for review.
    """
    import cv2
    q,t = np.asarray(query,float),np.asarray(target,float)
    reasons = []
    if q.ndim!=2 or q.shape!=t.shape or q.shape[1]!=2 or not np.isfinite(q).all() or not np.isfinite(t).all():
        raise ValueError("Finite paired image points required")
    if len(q)>50000 or len(np.unique(q,axis=0))!=len(q) or len(np.unique(t,axis=0))!=len(t):
        raise ValueError("Distinct bounded image correspondences required")
    result = {"status":"withheld","match_count":len(q),"reasons":reasons}
    if len(q) < minimum:
        reasons.append("insufficient_distinct_matches")
        return result
    h,w = shape
    cells = np.floor(q/[w/4,h/4]).astype(int)
    held = (cells[:,0]+cells[:,1])%3 == 0
    if held.sum()<8 or (~held).sum()<12:
        reasons.append("insufficient_spatial_holdouts")
        return result
    if np.linalg.matrix_rank(q[~held]-q[~held].mean(0))<2:
        reasons.append("collinear_controls")
        return result
    cv2.setRNGSeed(41)
    matrix, mask = cv2.estimateAffine2D(q[~held],t[~held],method=cv2.RANSAC,
                                      ransacReprojThreshold=tolerance,maxIters=5000,
                                      confidence=.999,refineIters=10)
    if matrix is None:
        reasons.append("no_affine_consensus")
        return result
    inliers = mask.ravel().astype(bool)
    errors = np.linalg.norm(q@matrix[:,:2].T+matrix[:,2]-t,axis=1)
    checked = errors[held]
    passed = checked <= tolerance
    sv = np.linalg.svd(matrix[:,:2],compute_uv=False)
    spread = np.ptp(q[~held][inliers],axis=0)/[w,h]
    result.update(matrix=matrix.tolist(),control_points=q[~held].tolist(),control_targets=t[~held].tolist(),
                  checkpoint_points=q[held].tolist(),checkpoint_targets=t[held].tolist(),
                  control_inliers=int(inliers.sum()),control_fraction=float(inliers.mean()),
                  checkpoint_count=int(held.sum()),checkpoint_fraction=float(passed.mean()),
                  checkpoint_rms=float(np.sqrt(np.mean(checked[passed]**2))) if passed.any() else None,
                  checkpoint_p90=float(np.percentile(checked,90)),spread=spread.tolist(),
                  anisotropy=float(sv[0]/sv[-1]) if sv[-1]>0 else None)
    if inliers.sum()<16 or inliers.mean()<.7:
        reasons.append("weak_control_consensus")
    if passed.mean()<.8 or not passed.any() or result["checkpoint_rms"]>tolerance/2:
        reasons.append("withheld_checkpoint_error")
    if np.any(spread<.65):
        reasons.append("limited_control_extent")
    if np.linalg.det(matrix[:,:2])<=0 or sv[-1]<=0 or sv[0]/sv[-1]>1.05:
        reasons.append("reflection_or_affine_distortion")
    if not reasons:
        result["status"]="geometric_candidate"
    return result


def image_agreement(image, reference, known, matrix):
    """Compare image content across the projected view, including reference holes."""
    import cv2
    h,w = image.shape[:2]
    rh,rw = reference.shape[:2]
    corners = np.array([[-.5,-.5],[w-.5,-.5],[w-.5,h-.5],[-.5,h-.5]])@matrix[:,:2].T+matrix[:,2]
    inside = bool(np.all(corners[:,0]>=-.5) and np.all(corners[:,1]>=-.5)
                  and np.all(corners[:,0]<=rw-.5) and np.all(corners[:,1]<=rh-.5))
    mask = cv2.warpAffine(np.ones((h,w),np.uint8),matrix,(rw,rh),flags=cv2.INTER_NEAREST).astype(bool)
    count = int(mask.sum())
    valid = mask & known
    scale = np.sqrt(abs(np.linalg.det(matrix[:,:2])))
    sigma = max(0.,(.5/scale)-.5) if scale>0 else 0
    gray = cv2.cvtColor(image,cv2.COLOR_RGB2GRAY)
    if sigma>.1:
        gray = cv2.GaussianBlur(gray,(0,0),min(sigma,30))
    warped = cv2.warpAffine(gray,matrix,(rw,rh),flags=cv2.INTER_LINEAR)
    other = cv2.cvtColor(reference,cv2.COLOR_RGB2GRAY)
    corr = None
    if valid.sum()>=64 and warped[valid].std()>1 and other[valid].std()>1:
        corr = float(np.corrcoef(warped[valid],other[valid])[0,1])
    return {"whole_view_inside_reference":inside,"known_reference_fraction":float(valid.sum()/count) if count else 0,
            "compared_pixels":int(valid.sum()),"gray_correlation":corr,"reference_corners":corners.tolist()}


def feature_points(image, *, long_side=1024, features=6000):
    import cv2
    scale = min(1.,long_side/max(image.shape[:2]))
    h,w = image.shape[:2]
    resized = cv2.resize(image,(max(1,round(w*scale)),max(1,round(h*scale))))
    sift = cv2.SIFT_create(nfeatures=features,contrastThreshold=.02)
    key,desc = sift.detectAndCompute(cv2.cvtColor(resized,cv2.COLOR_RGB2GRAY),None)
    points = np.asarray([p.pt for p in key],float).reshape(-1,2)
    return resized_points(points,(h,w),resized.shape[:2]),desc


def resized_points(points, original_shape, resized_shape):
    """Invert resize using pixel centres and actual integer output dimensions."""
    h,w = original_shape
    rh,rw = resized_shape
    return (np.asarray(points)+.5)/np.array([rw/w,rh/h])-.5


def match_points(points, desc, target_points, target_desc):
    import cv2
    if desc is None or target_desc is None or len(target_desc)<2:
        return np.empty((0,2)),np.empty((0,2))
    cv2.setRNGSeed(41)
    matcher = cv2.FlannBasedMatcher(dict(algorithm=1,trees=5),dict(checks=96))
    neighbours = matcher.knnMatch(desc,target_desc,k=2)
    candidates = sorted([a for pair in neighbours if len(pair)==2 for a,b in [pair] if a.distance<.7*b.distance],key=lambda m:m.distance)
    query_seen,target_seen = set(),set()
    q,t = [],[]
    for m in candidates:
        qp,tp = points[m.queryIdx],target_points[m.trainIdx]
        qkey,tkey = tuple(np.round(qp,1)),tuple(np.round(tp,1))
        if qkey in query_seen or tkey in target_seen:
            continue
        query_seen.add(qkey);target_seen.add(tkey)
        q.append(qp);t.append(tp)
    return np.asarray(q).reshape(-1,2),np.asarray(t).reshape(-1,2)


def audit(dataset, reference_archive, output, *, long_side=1024):
    import cv2
    cv2.setNumThreads(2)
    if type(long_side) is not int or not 128<=long_side<=2048:
        raise ValueError("Invalid image matching size")
    if output.exists():
        raise ValueError("Use a fresh audit output directory")
    output.mkdir(parents=True)
    reference,known,affine = load_reference_mosaic(reference_archive)
    enlarged = cv2.resize(reference,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
    mask = cv2.erode(cv2.resize(known.astype(np.uint8)*255,None,fx=2,fy=2,interpolation=cv2.INTER_NEAREST),np.ones((9,9),np.uint8))
    sift = cv2.SIFT_create(nfeatures=24000,contrastThreshold=.02)
    rk,rd = sift.detectAndCompute(cv2.cvtColor(enlarged,cv2.COLOR_RGB2GRAY),mask)
    rp = resized_points(np.asarray([p.pt for p in rk],float),reference.shape[:2],enlarged.shape[:2])
    reports = []
    with zipfile.ZipFile(dataset) as source:
        manifest = json.loads(source.read("manifest.json"))
        for record in manifest["samples"]:
            if record.get("georef"):
                continue
            image = np.asarray(Image.open(io.BytesIO(source.read(record["image"]))).convert("RGB"))
            labels = np.asarray(Image.open(io.BytesIO(source.read(record["labels"]))).convert("L"))
            if labels.shape!=image.shape[:2]:
                raise ValueError("Image/mask shape mismatch")
            if labels.size>4_000_000:
                raise ValueError("View pixel budget exceeded")
            points,desc = feature_points(image,long_side=long_side)
            q,t = match_points(points,desc,rp,rd)
            row = fit_correspondences(q,t,image.shape[:2])
            row.update(sample_id=record["sample_id"],image_sha256=hashlib.sha256(source.read(record["image"])).hexdigest(),
                       labels_sha256=hashlib.sha256(source.read(record["labels"])).hexdigest(),
                       image_shape=list(image.shape[:2]),label_counts={str(k):int(v) for k,v in zip(*np.unique(labels,return_counts=True))})
            if row.get("matrix"):
                agreement = image_agreement(image,reference,known,np.asarray(row["matrix"]))
                row["image_agreement"]=agreement
                if not agreement["whole_view_inside_reference"] or agreement["known_reference_fraction"]<.99:
                    row["reasons"].append("incomplete_reference_coverage")
                if agreement["gray_correlation"] is None or agreement["gray_correlation"]<.85:
                    row["reasons"].append("weak_image_agreement")
            if row["status"]=="geometric_candidate" and not row["reasons"]:
                row["status"]="validated_relative_candidate"
            elif row["reasons"]:
                row["status"]="withheld"
            reports.append(row)
            print(record["sample_id"],row["status"],row["reasons"],flush=True)
    report = {"schema":"voxel-view-registration-audit-v1","dataset_sha256":hashlib.sha256(dataset.read_bytes()).hexdigest(),
              "reference_archive_sha256":hashlib.sha256(reference_archive.read_bytes()).hexdigest(),
              "reference_crs":"EPSG:27700","reference_transform":list(affine)[:6],
              "reference_shape":list(reference.shape[:2]),"known_reference_pixels":int(known.sum()),
              "query_long_side":long_side,
              "views":reports,"georeferences_written":0,"world_blocks_changed":0,
              "policy":"Direct source-relative candidates only; no chained georeferencing, survey accuracy claim, label creation or automatic world edits."}
    (output/"audit.json").write_text(json.dumps(report,indent=2))
    return report


def apply_review(dataset, reference_archive, primary, repeat, review, output, *, buffer_m=32.):
    """Admit explicitly reviewed, repeatable direct fits; retain original bytes.

    The review selects IDs, not new control coordinates. Saved correspondences
    and image agreement are replayed. Existing accepted transforms stay intact.
    """
    from affine import Affine
    from shapely.geometry import Polygon
    dataset_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    reference_hash = hashlib.sha256(reference_archive.read_bytes()).hexdigest()
    if output.resolve()==dataset.resolve() or output.exists():
        raise ValueError("Use a fresh derivative archive")
    if not np.isfinite(buffer_m) or buffer_m<0:
        raise ValueError("Invalid geographic grouping buffer")
    for report in (primary,repeat):
        if report["dataset_sha256"]!=dataset_hash or report["reference_archive_sha256"]!=reference_hash:
            raise ValueError("Audit source hashes differ")
    if primary.get("query_long_side",1024)==repeat.get("query_long_side",1024):
        raise ValueError("Different matching scales required for repeatability")
    if review.get("dataset_sha256")!=dataset_hash or review.get("reference_archive_sha256")!=reference_hash or review.get("visual_alignment_reviewed") is not True:
        raise ValueError("Source-bound visual review required")
    selected = set(review["accepted_ids"])
    if len(selected)!=len(review["accepted_ids"]) or not selected:
        raise ValueError("Distinct reviewed sample IDs required")
    index = {r["sample_id"]:r for r in primary["views"]}
    other = {r["sample_id"]:r for r in repeat["views"]}
    reference,known,base = load_reference_mosaic(reference_archive)
    transforms = {}
    for sid in sorted(selected):
        row,second = index[sid],other[sid]
        if any(r["status"]!="validated_relative_candidate" or r["reasons"] for r in (row,second)):
            raise ValueError("Reviewed sample did not pass candidate gates")
        for candidate in (row,second):
            if candidate["image_shape"]!=row["image_shape"]:
                raise ValueError("Matching scale image shapes differ")
            q = np.asarray(candidate["control_points"]+candidate["checkpoint_points"])
            t = np.asarray(candidate["control_targets"]+candidate["checkpoint_targets"])
            replay = fit_correspondences(q,t,candidate["image_shape"])
            if replay["status"]!="geometric_candidate" or not np.allclose(replay["matrix"],candidate["matrix"],atol=1e-7,rtol=0):
                raise ValueError("Registration point evidence failed replay")
        matrix,second_matrix = np.asarray(row["matrix"]),np.asarray(second["matrix"])
        h,w = row["image_shape"]
        corners = np.array([[0,0],[w,0],[w,h],[0,h]])
        drift = float(np.max(np.linalg.norm(corners@(matrix[:,:2]-second_matrix[:,:2]).T+matrix[:,2]-second_matrix[:,2],axis=1)))
        if drift>.5:
            raise ValueError("Matching scales disagree at view corners")
        transforms[sid] = (matched_georef(base,matrix),drift)
    temporary = output.with_suffix(output.suffix+".tmp")
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with zipfile.ZipFile(dataset) as src,zipfile.ZipFile(temporary,"w",zipfile.ZIP_DEFLATED) as dst:
            manifest = json.loads(src.read("manifest.json"))
            records = manifest["samples"]
            found = set()
            for record in records:
                sid = record["sample_id"]
                if sid not in selected:
                    continue
                if record.get("georef"):
                    raise ValueError("Refusing to replace existing registration")
                row = index[sid]
                if hashlib.sha256(src.read(record["image"])).hexdigest()!=row["image_sha256"] or hashlib.sha256(src.read(record["labels"])).hexdigest()!=row["labels_sha256"]:
                    raise ValueError("Reviewed sample bytes changed")
                image = np.asarray(Image.open(io.BytesIO(src.read(record["image"]))).convert("RGB"))
                agreement = image_agreement(image,reference,known,np.asarray(row["matrix"]))
                if not agreement["whole_view_inside_reference"] or agreement["known_reference_fraction"]<.99 or agreement["gray_correlation"] is None or agreement["gray_correlation"]<.85:
                    raise ValueError("Image agreement failed replay")
                affine,drift = transforms[sid]
                record["georef"]={"crs":"EPSG:27700","transform":list(affine)[:6]}
                record["georef_provenance"]={"method":"reviewed_direct_affine_image_match_with_spatial_holdouts",
                    "reference_archive_sha256":reference_hash,"relative_uncertainty_m":1.,
                    "uncertainty_interpretation":"Minimum source-relative allowance, not an independently calibrated error bound",
                    "checkpoint_rms_m":row["checkpoint_rms"],"checkpoint_fraction":row["checkpoint_fraction"],
                    "two_scale_corner_drift_m":drift,"image_gray_correlation":agreement["gray_correlation"],
                    "accuracy_scope":"source-relative raster alignment; absolute survey accuracy and capture date unverified"}
                record.pop("context",None);record.pop("context_provenance",None)
                found.add(sid)
            if found!=selected:
                raise ValueError("Reviewed IDs absent from dataset")
            # Preserve original source grouping and join image footprints within
            # the metric buffer. Unregistered views cannot enter geographic runs.
            parent = list(range(len(records)))
            def root(i):
                while parent[i]!=i:
                    parent[i]=parent[parent[i]];i=parent[i]
                return i
            def join(a,b):
                parent[root(b)]=root(a)
            groups = {}
            footprints = []
            for i,record in enumerate(records):
                old = record.get("split_group")
                if old:
                    if old in groups:join(i,groups[old])
                    else:groups[old]=i
                if record.get("georef"):
                    if record["georef"]["crs"]!="EPSG:27700":
                        raise ValueError("One metric CRS required for geographic groups")
                    with Image.open(io.BytesIO(src.read(record["image"]))) as image:w,h=image.size
                    tf = Affine(*record["georef"]["transform"])
                    uncertainty = float(record.get("georef_provenance",{}).get("relative_uncertainty_m",0))
                    if not np.isfinite(uncertainty) or uncertainty<0:
                        raise ValueError("Invalid registration uncertainty")
                    footprints.append((i,Polygon([tf*p for p in ((0,0),(w,0),(w,h),(0,h))]),uncertainty))
            for k,(i,a,ua) in enumerate(footprints):
                for j,b,ub in footprints[k+1:]:
                    if a.distance(b)<=buffer_m+ua+ub:join(i,j)
            components = {}
            for i,record in enumerate(records):
                if record.get("georef"):
                    components.setdefault(root(i),[]).append(record["sample_id"])
            names = {key:"geographic_"+hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()[:12] for key,ids in components.items()}
            for i,record in enumerate(records):
                if record.get("georef"):
                    record["original_split_group"]=record.get("split_group")
                    record["split_group"]=names[root(i)]
            summary = {"accepted_relative_views":len(found),"registered_total":len(footprints),
                       "remaining_unregistered":len(records)-len(footprints),"buffer_m":buffer_m,
                       "buffer_policy":"Requested separation plus both relative registration uncertainties",
                       "geographic_groups":{names[k]:sorted(ids) for k,ids in components.items()},
                       "policy":"Groups are conservative overlap/source groups, not independent acquisitions. Unknown registrations must be filtered before geographic evaluation."}
            manifest["registration_filter_required"]=True
            manifest["view_registration_report"]=summary
            if "georef_report" in manifest:
                manifest["georef_report"]["scope"]="Historical exact-match recovery; current coverage is in view_registration_report"
            for item in src.infolist():
                if item.filename!="manifest.json":dst.writestr(copy.copy(item),src.read(item))
            dst.writestr("manifest.json",json.dumps(manifest,indent=2))
            dst.writestr("registration-audit/primary.json",json.dumps(primary,indent=2))
            dst.writestr("registration-audit/repeat.json",json.dumps(repeat,indent=2))
            dst.writestr("registration-audit/review.json",json.dumps(review,indent=2))
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return summary
