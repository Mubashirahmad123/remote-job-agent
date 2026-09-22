"""patch_curator.py - Apply multi-CV changes to agents/curator.py"""
import sys

with open('agents/curator.py', 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# 1. Add cv_library import
OLD = 'from tools.yield_tracker import YieldTracker, count_by_source\n'
NEW = 'from tools.yield_tracker import YieldTracker, count_by_source\nfrom tools.cv_library import get_library as _get_cv_library\n'
if OLD in content:
    content = content.replace(OLD, NEW, 1)
    changes += 1
    print('[1] cv_library import added')
else:
    print('[1] ERROR: cv_library import target not found')

# 2. Add CVLibrary init block after CV_PATH block
OLD2 = '    else:\n        print(f"\u26a0\ufe0f CV not found: {cv_path}")\n\n\n# =============================================================================\n# REJECTION ENGINE'
NEW2 = '''    else:
        print(f"\u26a0\ufe0f CV not found: {cv_path}")

# ------------------------------------------------------------------
# Multi-CV library (Feature 3: Personalisation)
# Activated when CV_DIR is set; falls back to single CV_PATH otherwise.
# ------------------------------------------------------------------
print("\\n\u2728 Loading CV library...")
_CV_LIBRARY = _get_cv_library()
if not _CV_LIBRARY.is_empty:
    _CV_LIBRARY.summary()

# If CV_DIR provided CVs but no single CV_PATH gave a primary profile,
# use the first registered CV as the backward-compat CV_PROFILE.
if not CV_MATCHING_ENABLED and not _CV_LIBRARY.is_empty:
    _CV_LIBRARY._ensure_parsed(_CV_LIBRARY.cvs[0])
    _primary = _CV_LIBRARY.cvs[0]["profile"]
    if _primary:
        CV_PROFILE = _primary
        CV_MATCHING_ENABLED = True
        print(f"\u2705 CV matching enabled via CV_DIR (min score: {MIN_SCORE})")


# =============================================================================
# REJECTION ENGINE'''
if OLD2 in content:
    content = content.replace(OLD2, NEW2, 1)
    changes += 1
    print('[2] CVLibrary init block added')
else:
    print('[2] ERROR: CV_PATH block tail not found — searching...')
    idx = content.find('CV not found: {cv_path}')
    print(f'    "CV not found" found at index: {idx}')
    print(f'    Context: {repr(content[max(0,idx-5):idx+60])}')

# 3. Replace scoring block with multi-CV aware version
# Locate the exact block between REJECTION CHECK and the freshness boost
OLD3 = (
    '        # === CV SCORING (uses cv_matcher.py) ===\n'
    '        keyword_score = 0\n'
    '        semantic_score = 0\n'
    '        semantic_computed = False\n'
    '        match_reason = "No CV matching"\n'
    '        \n'
    '        if CV_MATCHING_ENABLED and CV_PROFILE:\n'
    '            matcher = _get_cv_matcher()\n'
    '            if matcher:\n'
    '                score_result = matcher.score(job)\n'
    '                keyword_score = score_result.get("score", 0)\n'
    '                match_reason = score_result.get("match_reason", "")\n'
    '            \n'
    '            # Semantic scoring (Phase 2)\n'
    '            if SEMANTIC_AVAILABLE and CV_EMBEDDINGS:\n'
    '                try:\n'
    '                    semantic_score = score_semantic(job, CV_EMBEDDINGS)\n'
    '                    semantic_computed = True\n'
    '                except Exception as e:\n'
    '                    print(f"   \u26a0\ufe0f Semantic scoring failed for {job.get(\'job_title\', \'\')[:40]}: {e}")\n'
    '        \n'
    '        # Freshness boost (ranking only \u2014 never gates the threshold)\n'
)

NEW3 = (
    '        # === CV SCORING (uses cv_matcher.py) ===\n'
    '        keyword_score = 0\n'
    '        semantic_score = 0\n'
    '        semantic_computed = False\n'
    '        match_reason = "No CV matching"\n'
    '\n'
    '        # --- Multi-CV: pick the best CV for this specific job ---\n'
    '        selected_cv_path = ""\n'
    '        selected_cv_name = ""\n'
    '        scoring_profile = CV_PROFILE  # fallback to global primary profile\n'
    '\n'
    '        if not _CV_LIBRARY.is_empty:\n'
    '            picked_path, picked_profile, _ = _CV_LIBRARY.pick_best(job)\n'
    '            if picked_path and picked_profile:\n'
    '                selected_cv_path = picked_path\n'
    '                selected_cv_name = Path(picked_path).name\n'
    '                scoring_profile = picked_profile\n'
    '\n'
    '        if CV_MATCHING_ENABLED and scoring_profile:\n'
    '            from tools.cv_matcher import CVMatcher as _CVMatcher\n'
    '            scorer = _CVMatcher(scoring_profile)\n'
    '            score_result = scorer.score(job)\n'
    '            keyword_score = score_result.get("score", 0)\n'
    '            match_reason = score_result.get("match_reason", "")\n'
    '\n'
    '            # Semantic scoring (Phase 2) \u2014 always uses the primary CV embeddings\n'
    '            if SEMANTIC_AVAILABLE and CV_EMBEDDINGS:\n'
    '                try:\n'
    '                    semantic_score = score_semantic(job, CV_EMBEDDINGS)\n'
    '                    semantic_computed = True\n'
    '                except Exception as e:\n'
    '                    print(f"   \u26a0\ufe0f Semantic scoring failed for {job.get(\'job_title\', \'\')[:40]}: {e}")\n'
    '\n'
    '        # Freshness boost (ranking only \u2014 never gates the threshold)\n'
)

if OLD3 in content:
    content = content.replace(OLD3, NEW3, 1)
    changes += 1
    print('[3] Scoring block replaced')
else:
    print('[3] ERROR: scoring block not found')
    idx = content.find('# === CV SCORING (uses cv_matcher.py) ===')
    print(f'    "CV SCORING" comment at index: {idx}')
    print(f'    Context snippet: {repr(content[idx:idx+200])}')

# 4. Add selected_cv fields after freshness_boost line
OLD4 = (
    '        job["match_reason"] = match_reason\n'
    '        job["freshness_boost"] = freshness\n'
    '        \n'
    '        if base_score < MIN_SCORE:\n'
)
NEW4 = (
    '        job["match_reason"] = match_reason\n'
    '        job["freshness_boost"] = freshness\n'
    '        # Attach selected CV so downstream steps (auto_applier, gemini_tools) can use it\n'
    '        job["selected_cv_path"] = selected_cv_path\n'
    '        job["selected_cv"] = selected_cv_name\n'
    '\n'
    '        if base_score < MIN_SCORE:\n'
)
if OLD4 in content:
    content = content.replace(OLD4, NEW4, 1)
    changes += 1
    print('[4] selected_cv fields added')
else:
    print('[4] ERROR: freshness_boost block not found')

with open('agents/curator.py', 'w', encoding='utf-8') as f:
    f.write(content)

print(f'\nDone: {changes}/4 changes applied')
if changes < 4:
    sys.exit(1)
